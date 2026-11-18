"""Run at Python's start-up by ovos_network_log.pth, in every process of this
environment: switches the network log on in OVOS' own processes. It must
never break a start-up, so anything that goes wrong is left alone."""
try:
    from ovos_network_log import install, prune, wanted
    if wanted():
        install()
        prune()
except Exception:   # pragma: no cover
    pass
