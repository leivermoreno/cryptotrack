from django.http import HttpResponse
from django.views.decorators.http import require_GET


@require_GET
def healthz(request):
    """Liveness probe for the platform health check.

    Deliberately minimal: returns a plain ``200 ok`` and touches no external
    dependency (no DB, cache, or CoinGecko call). It only confirms the WSGI
    process is up and serving requests. A readiness check that queried the DB
    would let a transient DB blip mark the whole app unhealthy and get it
    killed/restarted, so liveness is kept dependency-free on purpose.

    Auth- and CSRF-free by construction: GET-only and no session/user access.
    In production it is added to ``SECURE_REDIRECT_EXEMPT`` so an internal
    plaintext-HTTP probe is not answered with a 301 to HTTPS.
    """
    return HttpResponse("ok", content_type="text/plain")
