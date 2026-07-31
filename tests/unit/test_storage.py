"""
Miru Assistant — 存储层单元测试。

测试覆盖:
    - 数据库创建与迁移
    - GroupRepository CRUD
    - MessageRepository 插入/查询/去重/批量
    - ReportRepository 日报/条目
    - RunLogRepository
    - ConfigStoreRepository
"""

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from miru.storage.database import Database
from miru.storage.migrations import get_current_version, run_migrations
from miru.storage.models import (
    ChatGroup,
    ConfigStore,
    DailyReport,
    RawMessage,
    ReportItem,
    RunLog,
    now_ts,
)
from miru.storage.repository import (
    ConfigStoreRepository,
    GroupRepository,
    MessageRepository,
    ReportRepository,
    RunLogRepository,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_path():
    """在临时目录创建数据库路径。"""
    tmp = tempfile.mkdtemp()
    db_file = os.path.join(tmp, "test_miru.db")
    yield db_file
    # 清理
    try:
        for f in Path(tmp).glob("test_miru*"):
            f.unlink()
        os.rmdir(tmp)
    except Exception:
        pass


@pytest.fixture
def db(db_path):
    """创建并初始化数据库。"""
    database = Database(db_path)
    run_migrations(database)
    yield database
    database.close()


@pytest.fixture
def groups(db):
    """提供 GroupRepository。"""
    return GroupRepository(db)


@pytest.fixture
def messages(db):
    """提供 MessageRepository。"""
    return MessageRepository(db)


@pytest.fixture
def reports(db):
    """提供 ReportRepository。"""
    return ReportRepository(db)


@pytest.fixture
def run_logs(db):
    """提供 RunLogRepository。"""
    return RunLogRepository(db)


@pytest.fixture
def config_store(db):
    """提供 ConfigStoreRepository。"""
    return ConfigStoreRepository(db)


# ============================================================
# Test: Database Creation & Migration
# ============================================================

class TestDatabaseCreation:
    """测试数据库创建和迁移。"""

    def test_database_connects(self, db):
        """数据库连接成功。"""
        assert db.is_connected()

    def test_schema_version_is_1(self, db):
        """迁移后 schema_version = 1。"""
        assert get_current_version(db) == 1

    def test_all_tables_exist(self, db):
        """所有 V1 表都已创建。"""
        expected = [
            "chat_groups",
            "raw_messages",
            "daily_reports",
            "report_items",
            "run_log",
            "config_store",
            "db_metadata",
        ]
        rows = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        actual = [r["name"] for r in rows]
        for table in expected:
            assert table in actual, f"表 {table} 未创建"

    def test_todos_not_created(self, db):
        """V2 的 todos 表不应存在。"""
        row = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='todos'"
        ).fetchone()
        assert row is None, "V1 不应该创建 todos 表"

    def test_migration_idempotent(self, db):
        """迁移可以安全重复执行。"""
        v1 = get_current_version(db)
        run_migrations(db)  # 再跑一次
        v2 = get_current_version(db)
        assert v1 == v2 == 1

    def test_db_file_created(self, db_path):
        """数据库文件确实被创建。"""
        # 需要新连接来验证文件存在
        db2 = Database(db_path)
        run_migrations(db2)
        assert os.path.exists(db_path)
        assert os.path.getsize(db_path) > 0
        db2.close()


# ============================================================
# Test: GroupRepository
# ============================================================

class TestGroupRepository:
    """测试群组仓库。"""

    def test_insert_group(self, groups):
        """插入一个新群。"""
        g = ChatGroup(
            group_name="测试群",
            wechat_username="123456@chatroom",
            member_count=30,
        )
        result = groups.insert_or_update(g)
        assert result.id is not None
        assert result.id > 0
        assert result.group_name == "测试群"
        assert result.first_seen_at is not None

    def test_insert_duplicate_updates(self, groups):
        """重复插入同一个 wechat_username 会更新而非重复。"""
        g1 = ChatGroup(
            group_name="测试群",
            wechat_username="dup@chatroom",
            member_count=30,
        )
        r1 = groups.insert_or_update(g1)

        g2 = ChatGroup(
            group_name="测试群-改名后",
            wechat_username="dup@chatroom",
            member_count=35,
        )
        r2 = groups.insert_or_update(g2)

        # 应该是同一条记录
        assert r1.id == r2.id
        # member_count 被更新
        assert r2.member_count == 35

        # 数据库中只有一条
        all_groups = groups.get_all()
        matching = [g for g in all_groups if g.wechat_username == "dup@chatroom"]
        assert len(matching) == 1

    def test_get_active(self, groups):
        """get_active 只返回启用的群。"""
        groups.insert_or_update(ChatGroup(
            group_name="活跃群", wechat_username="active@chatroom", is_active=1,
        ))
        groups.insert_or_update(ChatGroup(
            group_name="停用群", wechat_username="inactive@chatroom", is_active=0,
        ))
        active = groups.get_active()
        names = [g.group_name for g in active]
        assert "活跃群" in names
        assert "停用群" not in names

    def test_get_by_wechat_username(self, groups):
        """按微信 username 查找。"""
        groups.insert_or_update(ChatGroup(
            group_name="查找群", wechat_username="findme@chatroom",
        ))
        found = groups.get_by_wechat_username("findme@chatroom")
        assert found is not None
        assert found.group_name == "查找群"

    def test_get_by_wechat_username_not_found(self, groups):
        """查找不存在的群返回 None。"""
        found = groups.get_by_wechat_username("nonexistent@chatroom")
        assert found is None

    def test_set_active(self, groups):
        """测试停用/启用切换。"""
        g = groups.insert_or_update(ChatGroup(
            group_name="切换群", wechat_username="toggle@chatroom", is_active=1,
        ))
        assert g.is_active == 1

        groups.set_active(g.id, False)
        found = groups.get_by_id(g.id)
        assert found.is_active == 0

        groups.set_active(g.id, True)
        found = groups.get_by_id(g.id)
        assert found.is_active == 1


# ============================================================
# Test: MessageRepository
# ============================================================

class TestMessageRepository:
    """测试消息仓库。"""

    def _make_group(self, groups, name="消息测试群", username="msgtest@chatroom"):
        return groups.insert_or_update(ChatGroup(
            group_name=name, wechat_username=username,
        ))

    def test_insert_single_message(self, groups, messages):
        """插入单条消息。"""
        g = self._make_group(groups)
        msg = RawMessage(
            msg_svr_id=1001,
            group_id=g.id,
            sender_name="张三",
            content_text="同学们好",
            msg_type=1,
            create_time=int(time.time()),
        )
        result = messages.insert(msg)
        assert result.id is not None
        assert result.msg_svr_id == 1001
        assert result.sender_name == "张三"

    def test_insert_duplicate_skipped(self, groups, messages):
        """重复 msg_svr_id 不会重复插入。"""
        g = self._make_group(groups)
        msg1 = RawMessage(
            msg_svr_id=2001, group_id=g.id, sender_name="李四",
            content_text="第一条", msg_type=1, create_time=int(time.time()),
        )
        r1 = messages.insert(msg1)

        msg2 = RawMessage(
            msg_svr_id=2001, group_id=g.id, sender_name="李四",
            content_text="重复的", msg_type=1, create_time=int(time.time()),
        )
        r2 = messages.insert(msg2)

        # 应该返回同一条记录
        assert r1.id == r2.id
        assert messages.count() == 1

    def test_batch_insert(self, groups, messages):
        """批量插入消息。"""
        g = self._make_group(groups)
        msgs = [
            RawMessage(
                msg_svr_id=3001 + i, group_id=g.id,
                sender_name=f"用户{i}", content_text=f"消息{i}",
                msg_type=1, create_time=int(time.time()) - 100 + i,
            )
            for i in range(10)
        ]
        inserted = messages.insert_batch(msgs)
        assert inserted == 10
        assert messages.count() == 10

    def test_batch_insert_with_duplicates(self, groups, messages):
        """批量插入时自动跳过重复。"""
        g = self._make_group(groups)
        # 先插入 5 条
        msgs1 = [
            RawMessage(
                msg_svr_id=4001 + i, group_id=g.id,
                sender_name=f"用户{i}", content_text=f"消息{i}",
                msg_type=1, create_time=int(time.time()),
            )
            for i in range(5)
        ]
        messages.insert_batch(msgs1)

        # 再插入 8 条（前 5 条重复）
        msgs2 = [
            RawMessage(
                msg_svr_id=4001 + i, group_id=g.id,
                sender_name=f"用户{i}", content_text=f"消息{i}",
                msg_type=1, create_time=int(time.time()),
            )
            for i in range(8)
        ]
        inserted = messages.insert_batch(msgs2)
        assert inserted == 3  # 只有后3条是新消息
        assert messages.count() == 8

    def test_get_by_group_with_time_range(self, groups, messages):
        """按群 + 时间范围查询。"""
        g = self._make_group(groups)
        base = int(time.time()) - 3600  # 1 小时前

        for i in range(5):
            messages.insert(RawMessage(
                msg_svr_id=5001 + i, group_id=g.id,
                sender_name="测试者", content_text=f"消息{i}",
                msg_type=1, create_time=base + i * 600,  # 每条间隔 10 分钟
            ))

        # 查询前 3 条 (base ~ base+1500, 不含 base+1800 那条)
        results = messages.get_by_group(
            g.id, start_time=base, end_time=base + 1500,
        )
        assert len(results) == 3

    def test_get_unprocessed(self, groups, messages):
        """查询未处理消息。"""
        g = self._make_group(groups)
        ts = int(time.time())

        # 插入 3 条未处理 + 1 条已处理
        for i in range(3):
            messages.insert(RawMessage(
                msg_svr_id=6001 + i, group_id=g.id,
                sender_name="A", content_text=f"未处理{i}",
                msg_type=1, create_time=ts + i,
            ))
        msg_processed = messages.insert(RawMessage(
            msg_svr_id=6100, group_id=g.id,
            sender_name="B", content_text="已处理",
            msg_type=1, create_time=ts,
            is_processed=1,
        ))

        unprocessed = messages.get_unprocessed(g.id)
        assert len(unprocessed) == 3
        for m in unprocessed:
            assert m.is_processed == 0

    def test_mark_processed(self, groups, messages):
        """标记消息为已处理。"""
        g = self._make_group(groups)
        ts = int(time.time())
        inserted = []
        for i in range(5):
            m = messages.insert(RawMessage(
                msg_svr_id=7001 + i, group_id=g.id,
                sender_name="C", content_text=f"msg{i}",
                msg_type=1, create_time=ts + i,
            ))
            inserted.append(m)

        ids_to_mark = [m.id for m in inserted[:3]]
        messages.mark_processed(ids_to_mark, report_id=1)

        # 验证前 3 条已处理
        for mid in ids_to_mark:
            m = messages.get_by_id(mid)
            assert m.is_processed == 1
            assert m.processed_in == 1

        # 后 2 条仍为未处理
        for mid in [m.id for m in inserted[3:]]:
            m = messages.get_by_id(mid)
            assert m.is_processed == 0

    def test_get_processed_svr_ids(self, groups, messages):
        """批量查询已存在的 svr_id。"""
        g = self._make_group(groups)
        ts = int(time.time())
        for i in range(10):
            messages.insert(RawMessage(
                msg_svr_id=8001 + i, group_id=g.id,
                sender_name="D", content_text=f"msg{i}",
                msg_type=1, create_time=ts,
            ))

        # 查询：前3个存在 + 3个不存在
        existing = messages.get_processed_svr_ids([8001, 8002, 8003, 9991, 9992, 9993])
        assert 8001 in existing
        assert 8002 in existing
        assert 8003 in existing
        assert 9991 not in existing
        assert len(existing) == 3

    def test_get_processed_svr_ids_empty(self, messages):
        """空列表查询返回空集合。"""
        result = messages.get_processed_svr_ids([])
        assert result == set()


# ============================================================
# Test: ReportRepository
# ============================================================

class TestReportRepository:
    """测试日报仓库。"""

    def test_insert_report(self, reports):
        """插入日报。"""
        r = DailyReport(
            report_date="2026-07-24",
            content_md="# 日报\n测试内容",
            stats_json='{"total":10}',
            groups_covered='["测试群"]',
            message_count=10,
        )
        result = reports.insert_report(r)
        assert result.id is not None
        assert result.report_date == "2026-07-24"
        assert result.push_status == "pending"

    def test_get_by_date(self, reports):
        """按日期查询。"""
        reports.insert_report(DailyReport(
            report_date="2026-07-20", content_md="日报内容",
        ))
        found = reports.get_by_date("2026-07-20")
        assert found is not None
        assert found.report_date == "2026-07-20"

        not_found = reports.get_by_date("2026-01-01")
        assert not_found is None

    def test_get_unpushed(self, reports):
        """查询未推送的日报。"""
        reports.insert_report(DailyReport(
            report_date="2026-07-21", content_md="1", push_status="sent",
        ))
        reports.insert_report(DailyReport(
            report_date="2026-07-22", content_md="2", push_status="failed",
        ))
        reports.insert_report(DailyReport(
            report_date="2026-07-23", content_md="3", push_status="pending",
        ))

        unpushed = reports.get_unpushed()
        dates = [r.report_date for r in unpushed]
        assert "2026-07-21" not in dates  # sent
        assert "2026-07-22" in dates      # failed
        assert "2026-07-23" in dates      # pending
        assert len(unpushed) == 2

    def test_update_push_status(self, reports):
        """更新推送状态。"""
        r = reports.insert_report(DailyReport(
            report_date="2026-07-25", content_md="测试",
        ))
        assert r.push_status == "pending"

        reports.update_push_status(r.id, "sent")
        updated = reports.get_by_id(r.id)
        assert updated.push_status == "sent"
        assert updated.pushed_at is not None

        reports.update_push_status(r.id, "failed", error="网络超时")
        updated = reports.get_by_id(r.id)
        assert updated.push_status == "failed"
        assert updated.push_error == "网络超时"

    def test_insert_and_get_items(self, reports):
        """插入并查询日报条目。"""
        r = reports.insert_report(DailyReport(
            report_date="2026-07-26", content_md="test",
        ))
        items = [
            ReportItem(
                report_id=r.id, category="通知",
                content="明天调课", source_group="班群",
                source_sender="老师", importance="high",
                action_required=1, sort_order=0,
            ),
            ReportItem(
                report_id=r.id, category="作业",
                content="习题 1-5", source_group="课程群",
                source_sender="助教", importance="medium",
                deadline="2026-07-30", action_required=1, sort_order=1,
            ),
        ]
        reports.insert_items(items)

        fetched = reports.get_items(r.id)
        assert len(fetched) == 2
        assert fetched[0].category == "通知"
        assert fetched[1].category == "作业"
        assert fetched[1].deadline == "2026-07-30"

    def test_get_latest(self, reports):
        """获取最近的日报。"""
        for i in range(10):
            reports.insert_report(DailyReport(
                report_date=f"2026-07-{10+i:02d}", content_md=f"日报{i}",
            ))
        latest = reports.get_latest(3)
        assert len(latest) == 3
        # 应该按日期倒序
        assert latest[0].report_date == "2026-07-19"


# ============================================================
# Test: RunLogRepository
# ============================================================

class TestRunLogRepository:
    """测试运行日志仓库。"""

    def test_insert_and_query(self, run_logs):
        """插入并查询运行日志。"""
        entry = RunLog(
            run_id="test-run-001",
            phase="collect",
            status="success",
            message="采集完成",
            duration_ms=1500,
        )
        result = run_logs.insert(entry)
        assert result.id is not None

        entries = run_logs.get_by_run_id("test-run-001")
        assert len(entries) == 1
        assert entries[0].phase == "collect"
        assert entries[0].status == "success"

    def test_get_recent(self, run_logs):
        """获取最近的运行日志。"""
        for i in range(5):
            run_logs.insert(RunLog(
                run_id=f"run-{i:03d}", phase="collect",
                status="success", message=f"第{i}次",
                duration_ms=1000,
            ))
        recent = run_logs.get_recent(3)
        assert len(recent) == 3


# ============================================================
# Test: ConfigStoreRepository
# ============================================================

class TestConfigStoreRepository:
    """测试配置快照仓库。"""

    def test_save_and_retrieve(self, config_store):
        """保存并检索配置快照。"""
        config_data = {
            "miru": {
                "groups": ["群1", "群2"],
                "llm": {"model": "deepseek-v4-flash"},
            }
        }
        snapshot_id = config_store.save_snapshot(config_data)
        assert snapshot_id > 0

        latest = config_store.get_latest()
        assert latest is not None
        assert "deepseek-v4-flash" in latest.config_snapshot
        # 验证 hash 一致
        import hashlib
        expected_hash = hashlib.sha256(
            json.dumps(config_data, ensure_ascii=False, indent=2).encode()
        ).hexdigest()
        assert latest.config_hash == expected_hash


# ============================================================
# Test: Integration — Cross-Repository
# ============================================================

class TestIntegration:
    """跨 Repository 集成测试。"""

    def test_full_message_flow(self, db):
        """模拟完整消息流: 群创建 → 消息插入 → 去重 → 标记已处理 → 生成日报。"""
        groups = GroupRepository(db)
        messages = MessageRepository(db)
        reports = ReportRepository(db)

        # 1. 创建群
        g = groups.insert_or_update(ChatGroup(
            group_name="集成测试群",
            wechat_username="integration@chatroom",
        ))

        # 2. 批量插入消息
        ts = int(time.time())
        msgs = [
            RawMessage(
                msg_svr_id=90001 + i, group_id=g.id,
                sender_name=f"用户{i}", content_text=f"消息内容{i}",
                msg_type=1, create_time=ts + i * 60,
            )
            for i in range(20)
        ]
        inserted = messages.insert_batch(msgs)
        assert inserted == 20

        # 3. 再次批量插入（应全跳过）
        inserted2 = messages.insert_batch(msgs)
        assert inserted2 == 0

        # 4. 查询未处理消息
        unprocessed = messages.get_unprocessed(g.id)
        assert len(unprocessed) == 20

        # 5. 生成日报
        r = reports.insert_report(DailyReport(
            report_date="2026-07-24",
            content_md="# 集成测试日报",
            stats_json=json.dumps({"total": 20}),
            groups_covered=json.dumps(["集成测试群"]),
            message_count=20,
        ))

        # 6. 添加日报条目并标记消息
        items = [
            ReportItem(
                report_id=r.id, category="通知",
                content=f"重要消息 {i}", source_group=g.group_name,
                source_sender=f"用户{i}", importance="high",
                action_required=1, sort_order=i,
            )
            for i in range(5)
        ]
        reports.insert_items(items)

        # 标记消息已处理
        msg_ids = [m.id for m in unprocessed]
        messages.mark_processed(msg_ids, r.id)

        # 7. 验证
        assert messages.get_unprocessed(g.id) == []
        fetched_items = reports.get_items(r.id)
        assert len(fetched_items) == 5
