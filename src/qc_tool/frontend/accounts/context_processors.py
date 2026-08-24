from qc_tool.frontend.accounts.authorization import access_for_request


def account_access(request):
    access = access_for_request(request)
    return {
        "account_access": access,
        # Compatibility for the existing base template.
        "can_change_password": access.can_change_password,
    }
