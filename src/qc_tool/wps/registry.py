#!/usr/bin/env python3


check_function_registry = {}

def register_check_function(ident, description=None):
    # If name is supplied with dots, take the last part.
    ident = ident.split(".")[-1]

    # Check if the function has already been registered.
    if ident in check_function_registry:
        raise Exception("An attemp to reregister function with ident='%s'.".format(ident))

    # Return decorator.
    def register(func):
        func.ident = ident
        func.description = description
        check_function_registry[ident] = func
        return func
    return register

def get_check_function(check_ident):
    return check_function_registry[check_ident]

def get_idents():
    return check_function_registry.keys()
