"""Bind one HTTP response, including lazy streams, to one database selection."""

from django.http import JsonResponse

from qc_tool.database import selection


class ScopedStream:
    def __init__(self, content, scope):
        self.content = content
        self.scope = scope

    def __iter__(self):
        iterator = iter(self.content)
        while True:
            with self.scope():
                try:
                    value = next(iterator)
                except StopIteration:
                    return
            yield value

    async def __aiter__(self):
        iterator = aiter(self.content)
        while True:
            with self.scope():
                try:
                    value = await anext(iterator)
                except StopAsyncIteration:
                    return
            yield value


def scope_response(response, scope):
    if response.streaming:
        content = ScopedStream(response.streaming_content, scope)
        response.streaming_content = content.__aiter__() if response.is_async else iter(content)
        original_close = response.close

        def close():
            with scope():
                original_close()

        response.close = close
    return response


class DatabaseScopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Liveness remains usable even when an operator must repair the pointer.
        if request.path_info == "/health" and request.method in {"GET", "HEAD"}:
            return self.get_response(request)
        try:
            name = selection.current_database()
        except selection.DatabaseSelectionError:
            return JsonResponse({
                "error": "database_selection_unavailable",
                "message": "Database selection is unavailable. Operator recovery is required.",
            }, status=503, headers={"Cache-Control": "no-store, private"})
        request.qc_database_name = name
        scope = lambda: selection.database_scope(name)
        with scope():
            response = self.get_response(request)
        return scope_response(response, scope)
