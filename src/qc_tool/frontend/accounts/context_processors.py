from qc_tool.frontend.accounts.authorization import access_for_request


def account_access(request):
    return {"account_access": access_for_request(request)}
