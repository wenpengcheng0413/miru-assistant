"""句级分块器测试（docs/02 §4 规则）。"""
from miru_server.core.splitter import SentenceSplitter


def test_boundary_split():
    sp = SentenceSplitter()
    out = sp.feed("今天天气不错。")
    assert out == ["今天天气不错。"]


def test_short_first_sentence_uses_first_min():
    sp = SentenceSplitter(first_min=6)
    assert sp.feed("好的。") == []           # 3 字 < first_min
    assert sp.feed("我马上来看看。") == ["好的。我马上来看看。"]  # 补足后一起出


def test_accumulate_until_boundary():
    sp = SentenceSplitter()
    assert sp.feed("今天有") == []
    assert sp.feed("三件事。") == ["今天有三件事。"]


def test_english_dot_is_not_boundary():
    sp = SentenceSplitter()
    assert sp.feed("圆周率是3.14左右") == []
    assert sp.flush(force=True) == ["圆周率是3.14左右"]


def test_max_len_hard_cut():
    sp = SentenceSplitter(max_len=60)
    long_text = "这是一段非常非常非常长的句子而且它完全没有标点符号" * 3
    out = sp.feed(long_text)
    assert out and len(out[0]) <= 61          # 可能带一个逗号
    assert "".join(out) + sp.pending() == long_text


def test_flush_requires_min_len_unless_forced():
    sp = SentenceSplitter(min_len=8)
    sp.feed("短")
    assert sp.flush(force=False) == []
    assert sp.flush(force=True) == ["短"]


def test_multiple_sentences_in_one_feed():
    sp = SentenceSplitter()
    out = sp.feed("这是第一句。第二句在这里啊。")
    assert out == ["这是第一句。", "第二句在这里啊。"]


def test_second_sentence_under_min_len_stays_pending():
    """第二句不足 min_len(8) 时留在缓冲，等后续增量或 flush。"""
    sp = SentenceSplitter()
    out = sp.feed("这是第一句。第二句。")   # 第二句只有 4 字
    assert out == ["这是第一句。"]
    assert sp.flush(force=True) == ["第二句。"]


def test_short_first_sentence_merges_into_next():
    """过短的首句（< first_min）与后文合并为一句，避免 TTS 碎句。"""
    sp = SentenceSplitter()
    out = sp.feed("好的。第二句在这里。")
    assert out == ["好的。第二句在这里。"]
