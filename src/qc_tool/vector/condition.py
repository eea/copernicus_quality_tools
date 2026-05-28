#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import logging
import re


DESCRIPTION = "Column value matches required condition"
IS_SYSTEM = False


log = logging.getLogger(__name__)


def convert_rule_to_sql_violation(rule_text):
    # Clean up the rule text and split by semicolons for multi-rule rows
    clauses = [c.strip() for c in rule_text.split(';') if c.strip()]
    
    operator_inversions = {
        '=': '<>',
        '>': '<=',
        '<': '>=',
        '>=': '<',
        '<=': '>',
        '<>': '='
    }
    
    sql_parts = []
    
    for clause in clauses:
        # Check if it's an IF/THEN rule
        if re.match(r'(?i)^if\s+', clause):
            match = re.match(r'(?i)if\s+(.*?)\s+then\s+(\w+)\s*([<=<>!]+|is)\s*(.*)', clause)
            if match:
                condition = match.group(1).strip()
                target_var = match.group(2).strip()
                operator = match.group(3).strip().lower()
                value = match.group(4).strip()
                
                if operator == 'is' and value.lower() == 'null':
                    violation_then = f"{target_var} IS NOT NULL"
                elif operator == 'is' and value.lower() == 'not null':
                    violation_then = f"{target_var} IS NULL"
                else:
                    inverted_op = operator_inversions.get(operator, operator)
                    violation_then = f"{target_var}{inverted_op}{value}"
                
                sql_parts.append(f"({condition} AND {violation_then})")
        
        # Otherwise, treat it as a direct mathematical constraint (e.g., A + B <= 100)
        else:
            # Match the left side, the operator, and the right side
            match = re.match(r'(.*?)\s*([<=<>!]+)\s*(.*)', clause)
            if match:
                left_side = match.group(1).strip()
                operator = match.group(2).strip()
                right_side = match.group(3).strip()
                
                inverted_op = operator_inversions.get(operator, operator)
                sql_parts.append(f"({left_side}{inverted_op}{right_side})")
            else:
                # Fallback if no operator is matched (e.g., raw text or unhandled format)
                sql_parts.append(f"NOT ({clause})")
                
    return " OR ".join(sql_parts)


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        log.debug("Started condition check for the layer {:s}.".format(layer_def["pg_layer_name"]))

        conditions = params["conditions"]
        for column_name, condition in conditions.items():
            error_where = convert_rule_to_sql_violation(condition)
            log.debug("Started condition check for the column {:s}.".format(column_name))

            # Prepare parameters used in sql clauses.
            sql_params = {"layer_name": layer_def["pg_layer_name"],
                          "fid_name": layer_def["pg_fid_name"],
                          "column_name": column_name,
                          "error_where": error_where}

            # Create table of error items.
            error_table = "s{:02d}_{:s}_condition_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"], column_name)
            sql = ("CREATE TABLE {error_table} ({fid_name} integer PRIMARY KEY);")
            sql = sql.format(error_table=error_table, **sql_params)
            cursor.execute(sql)
            sql = ("INSERT INTO {error_table}\n"
                   "SELECT {fid_name}\n"
                   "FROM {layer_name}\n"
                   "WHERE  ({error_where});")
            sql = sql.format(error_table=error_table, **sql_params)
            cursor.execute(sql)
            log.info("Error table {:s} has been inserted {:d} items.".format(error_table, cursor.rowcount))

            # Report error items.
            items_message = get_failed_items_message(cursor, error_table, layer_def["pg_fid_name"])
            if items_message is not None:
                status.failed("Layer {:s}, column {:s} has error rows violating the condition: '{:s}': {:s}."
                            .format(layer_def["pg_layer_name"], column_name, condition, items_message))
                status.add_error_table(error_table, layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        log.info("Condition check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))
