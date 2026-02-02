from django.http import JsonResponse


def health(request):
    """Health check endpoint - returns 200 OK."""
    return JsonResponse({"status": "ok"})
