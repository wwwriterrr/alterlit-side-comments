from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.notification.notifications import request_mode
from api.side_comments import feed


class SideCommentsView(APIView):
    """
    GET /api/v1/side_comments_v2/?v=<version>
        → 200 {"version": "...", "comments": [...]}  — лента сайта (по request.mode)
        → 304 без тела                                — v совпадает: ничего не изменилось
    Публичная, без сессии и CSRF: ответ из кеша, без запросов в БД.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        data = feed.get(request_mode(request))
        if request.query_params.get('v') == data['version']:
            return Response(status=304)
        response = Response(data)
        response['Cache-Control'] = 'no-cache'
        return response
