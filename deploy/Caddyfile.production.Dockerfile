# Miru production Caddy hardening overlay.
#
# The upstream Caddy binary carries cap_net_bind_service=ep so it can bind
# privileged ports. Miru listens on container port 8080 and drops every
# runtime capability. Linux rejects exec of a file-capability binary when the
# requested capability is outside the container bounding set, so remove the
# unnecessary file capability at image-build time.
FROM miru-caddy:98eb57d882cc

RUN setcap -r /usr/bin/caddy \
    && test -z "$(getcap /usr/bin/caddy)"
