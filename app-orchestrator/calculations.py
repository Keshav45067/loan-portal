import ast
import math
import random
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

def parse_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

def round_to(val: Any, step: float = 500.0) -> int:
    numeric_val = parse_float(val)
    step = parse_float(step)
    if step <= 0:
        return int(round(numeric_val))
    return int(round(numeric_val / step) * step)

def round_to_500(val: float) -> int:
    return round_to(val, 500.0)

def random_in_range(min_val: float, max_val: float) -> float:
    return random.uniform(parse_float(min_val), parse_float(max_val))

def years_since(date_val: Any, default: int = 1) -> int:
    if not date_val:
        return int(default)
    try:
        date_str = str(date_val).strip()
        if "-" in date_str:
            comm_year = datetime.strptime(date_str.split("T")[0], "%Y-%m-%d").year
        else:
            comm_year = int(date_str)
        current_year = datetime.now().year
        return max(0, current_year - comm_year + 1)
    except Exception:
        return int(default)

def clamp_growth(proposed_val: Any, base_val: Any, min_ratio: float = 1.1, max_ratio: float = 1.2) -> float:
    p_val = parse_float(proposed_val)
    b_val = parse_float(base_val)
    growth_ratio = (p_val / b_val) if b_val > 0 else 1.0
    if growth_ratio < min_ratio or growth_ratio > max_ratio:
        return random_in_range(min_ratio, max_ratio) * b_val
    return p_val

def clamp_growth_inverse(base_val: Any, past_val: Any, min_growth: float = 1.05, max_growth: float = 1.15, min_mult: float = 0.85, max_mult: float = 0.95) -> float:
    b_val = parse_float(base_val)
    p_val = parse_float(past_val)
    past_growth = (b_val / p_val) if p_val > 0 else 1.0
    if past_growth < min_growth or past_growth > max_growth:
        return random_in_range(min_mult, max_mult) * b_val
    return p_val

def clamp_range(ratio_val: Any, min_val: float = 0.40, max_val: float = 0.60, default: float = 0.5) -> float:
    r_val = parse_float(ratio_val)
    if r_val <= 0 or r_val < min_val or r_val > max_val:
        return random_in_range(min_val, max_val)
    return r_val

def match_keyword(text_val: Any, mapping_dict: Dict[str, Any], default: Any = 2) -> Any:
    text_str = str(text_val or "").lower()
    if isinstance(mapping_dict, dict):
        for k, v in mapping_dict.items():
            if str(k).lower() in text_str:
                return v
    return default

def if_gt(val: Any, threshold: Any, then_val: Any, else_val: Any) -> Any:
    return then_val if parse_float(val) > parse_float(threshold) else else_val

def if_zero(val: Any, then_val: Any, else_val: Any) -> Any:
    return then_val if parse_float(val) == 0 else else_val

def if_truthy(val: Any, then_val: Any, else_val: Any) -> Any:
    s_val = str(val or "").strip().lower()
    is_true = s_val in ("yes", "true", "1", "y", "t") or bool(val)
    return then_val if is_true else else_val

def if_match(text_val: Any, keywords_list: List[str], then_val: Any, else_val: Any) -> Any:
    text_str = str(text_val or "").lower()
    if isinstance(keywords_list, (list, tuple, set)):
        if any(str(kw).lower() in text_str for kw in keywords_list):
            return then_val
    return else_val

def min_non_zero(val1: Any, val2: Any) -> float:
    v1 = parse_float(val1)
    v2 = parse_float(val2)
    if v2 > 0 and v1 > v2:
        return v2
    return v1

def calc_inventory(calculated_inv: Any, inventory_amount: Any, proposed_rev: Any, current_rev: Any) -> float:
    input_inv = parse_float(calculated_inv)
    p_rev = parse_float(proposed_rev)
    c_rev = parse_float(current_rev)

    if input_inv > 0:
        base_inv = input_inv
    else:
        rev_ratio = (p_rev * 12 / (c_rev * 12)) if c_rev > 0 else 1.0
        base_inv = parse_float(inventory_amount) * rev_ratio

    inv_mult = base_inv / p_rev if p_rev > 0 else 0.0
    if 3.0 <= inv_mult <= 4.0:
        return float(int(round(base_inv)))
    else:
        return float(int(round(random_in_range(3.0, 4.0) * p_rev)))


PREDEFINED_FUNCTIONS = {
    "parse_float": parse_float,
    "round_to": round_to,
    "round_to_500": round_to_500,
    "random_in_range": random_in_range,
    "random_range": random_in_range,
    "years_since": years_since,
    "clamp_growth": clamp_growth,
    "clamp_growth_inverse": clamp_growth_inverse,
    "clamp_range": clamp_range,
    "match_keyword": match_keyword,
    "if_gt": if_gt,
    "if_zero": if_zero,
    "if_truthy": if_truthy,
    "if_match": if_match,
    "min_non_zero": min_non_zero,
    "calc_inventory": calc_inventory,
    "abs": abs,
    "min": min,
    "max": max,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
}


# ─── Safe AST Evaluator ───

class SafeExpressionEvaluator(ast.NodeVisitor):
    def __init__(self, context: Dict[str, Any]):
        self.context = context

    def visit_Name(self, node: ast.Name):
        if node.id in PREDEFINED_FUNCTIONS:
            return PREDEFINED_FUNCTIONS[node.id]
        if node.id in ("True", "False", "None"):
            return eval(node.id)
        return self.context.get(node.id, 0.0)

    def visit_Constant(self, node: ast.Constant):
        return node.value

    def visit_Num(self, node: ast.Num):
        return node.n

    def visit_Str(self, node: ast.Str):
        return node.s

    def visit_List(self, node: ast.List):
        return [self.visit(elt) for elt in node.elts]

    def visit_Tuple(self, node: ast.Tuple):
        return tuple(self.visit(elt) for elt in node.elts)

    def visit_Dict(self, node: ast.Dict):
        return {self.visit(k): self.visit(v) for k, v in zip(node.keys, node.values)}

    def visit_UnaryOp(self, node: ast.UnaryOp):
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return +operand
        elif isinstance(node.op, ast.USub):
            return -operand
        elif isinstance(node.op, ast.Not):
            return not operand
        raise ValueError(f"Unsupported unary operator: {type(node.op)}")

    def visit_BinOp(self, node: ast.BinOp):
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        elif isinstance(node.op, ast.Sub):
            return left - right
        elif isinstance(node.op, ast.Mult):
            return left * right
        elif isinstance(node.op, ast.Div):
            r = parse_float(right)
            return (parse_float(left) / r) if r != 0 else 0.0
        elif isinstance(node.op, ast.FloorDiv):
            r = parse_float(right)
            return (parse_float(left) // r) if r != 0 else 0.0
        elif isinstance(node.op, ast.Mod):
            r = parse_float(right)
            return (parse_float(left) % r) if r != 0 else 0.0
        elif isinstance(node.op, ast.Pow):
            return parse_float(left) ** parse_float(right)
        raise ValueError(f"Unsupported binary operator: {type(node.op)}")

    def visit_BoolOp(self, node: ast.BoolOp):
        if isinstance(node.op, ast.Or):
            for value in node.values:
                res = self.visit(value)
                if res:
                    return res
            return res
        elif isinstance(node.op, ast.And):
            for value in node.values:
                res = self.visit(value)
                if not res:
                    return res
            return res
        raise ValueError(f"Unsupported boolean operator: {type(node.op)}")

    def visit_Compare(self, node: ast.Compare):
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if isinstance(op, ast.Eq):
                matched = (left == right)
            elif isinstance(op, ast.NotEq):
                matched = (left != right)
            elif isinstance(op, ast.Lt):
                matched = (parse_float(left) < parse_float(right))
            elif isinstance(op, ast.LtE):
                matched = (parse_float(left) <= parse_float(right))
            elif isinstance(op, ast.Gt):
                matched = (parse_float(left) > parse_float(right))
            elif isinstance(op, ast.GtE):
                matched = (parse_float(left) >= parse_float(right))
            elif isinstance(op, ast.In):
                matched = (left in right) if right is not None else False
            elif isinstance(op, ast.NotIn):
                matched = (left not in right) if right is not None else True
            else:
                raise ValueError(f"Unsupported comparison operator: {type(op)}")
            if not matched:
                return False
            left = right
        return True

    def visit_Call(self, node: ast.Call):
        func = self.visit(node.func)
        args = [self.visit(arg) for arg in node.args]
        keywords = {kw.arg: self.visit(kw.value) for kw in node.keywords}
        if callable(func):
            return func(*args, **keywords)
        raise ValueError(f"Object {func} is not callable")

    def generic_visit(self, node):
        raise ValueError(f"Unsupported syntax: {type(node).__name__}")


def evaluate_expression(expr_str: str, context: Dict[str, Any]) -> Any:
    if not expr_str or not isinstance(expr_str, str):
        return expr_str
    expr_clean = expr_str.strip()
    if not expr_clean:
        return ""
    try:
        tree = ast.parse(expr_clean, mode="eval")
        evaluator = SafeExpressionEvaluator(context)
        return evaluator.visit(tree.body)
    except Exception as e:
        return expr_str


def calculate_derived_fields(state: dict, scheme_config: Optional[dict] = None) -> dict:
    """
    Calculate derived fields for a scheme.

    If scheme_config contains a 'derived_fields' mapping, rules are evaluated
    declaratively from YAML. Otherwise, falls back to default Mudra calculation logic.
    """
    derived = {}
    eval_context = state.copy()

    derived_rules = None
    if scheme_config and isinstance(scheme_config, dict):
        derived_rules = scheme_config.get("derived_fields")

    if derived_rules and isinstance(derived_rules, (dict, list)):
        rule_items = []
        if isinstance(derived_rules, dict):
            rule_items = list(derived_rules.items())
        elif isinstance(derived_rules, list):
            for r in derived_rules:
                if isinstance(r, dict) and "name" in r and "expression" in r:
                    rule_items.append((r["name"], r["expression"]))

        for field_name, expr in rule_items:
            try:
                val = evaluate_expression(expr, eval_context)
                derived[field_name] = val
                eval_context[field_name] = val
            except Exception as e:
                derived[field_name] = None

        return derived

    return {} # if no derived_fields found return empty dict

    # ─── Fallback Legacy Execution Path (if YAML block is omitted) ───
    # commencement_date = state.get("date_of_commencement")
    # if commencement_date:
    #     try:
    #         if "-" in str(commencement_date):
    #             comm_year = datetime.strptime(str(commencement_date).split("T")[0], "%Y-%m-%d").year
    #         else:
    #             comm_year = int(commencement_date)
    #         current_year = datetime.now().year
    #         derived["experience_in_line_of_activity"] = max(0, current_year - comm_year + 1)
    #     except Exception:
    #         derived["experience_in_line_of_activity"] = 1
    # else:
    #     derived["experience_in_line_of_activity"] = 1

    # business_type = str(state.get("business_type", "other")).lower()
    # is_livestock = any(t in business_type for t in ["goatory", "poultry", "dairy", "goatry"])
    # is_grocery_type = any(t in business_type for t in ["grocery", "stationary", "clothing"])

    # monthly_rev = parse_float(state.get("monthly_revenue"))
    # derived["net_sales_present_year"] = round_to_500(monthly_rev * 12)

    # raw_proposed_rev = parse_float(state.get("proposed_monthly_revenue"))
    # growth_ratio = (raw_proposed_rev / monthly_rev) if monthly_rev > 0 else 1.0
    # if growth_ratio < 1.1 or growth_ratio > 1.2:
    #     clamped_proposed_rev = random_in_range(1.1, 1.2) * monthly_rev
    # else:
    #     clamped_proposed_rev = raw_proposed_rev

    # derived["net_sales_next_year"] = round_to_500(clamped_proposed_rev * 12)
    # derived["proposed_monthly_revenue"] = clamped_proposed_rev

    # last_year_monthly_rev = parse_float(state.get("last_year_monthly_revenue"))
    # past_growth = (monthly_rev / last_year_monthly_rev) if last_year_monthly_rev > 0 else 1.0
    # if past_growth < 1.05 or past_growth > 1.15:
    #     adjusted_last_year_monthly_rev = random_in_range(0.85, 0.95) * monthly_rev
    # else:
    #     adjusted_last_year_monthly_rev = last_year_monthly_rev

    # derived["net_sales_past_year_1"] = round_to_500(adjusted_last_year_monthly_rev * 12)
    # derived["net_sales_past_year_2"] = round_to_500(random_in_range(0.85, 0.95) * adjusted_last_year_monthly_rev * 12)

    # raw_monthly_profit = parse_float(state.get("monthly_profit"))
    # profit_margin = (raw_monthly_profit / monthly_rev) if monthly_rev > 0 else 0.5
    # if profit_margin < 0.40 or profit_margin > 0.60:
    #     profit_margin = random_in_range(0.40, 0.60)

    # actual_monthly_profit = profit_margin * monthly_rev
    # derived["net_profit_present_year"] = round_to_500(actual_monthly_profit * 12)
    # derived["net_profit_past_year_1"] = round_to_500(profit_margin * adjusted_last_year_monthly_rev * 12)
    # derived["net_profit_past_year_2"] = round_to_500(profit_margin * random_in_range(0.85, 0.95) * adjusted_last_year_monthly_rev * 12)
    # derived["net_profit_next_year"] = round_to_500(profit_margin * clamped_proposed_rev * 12)

    # persons_involved = int(parse_float(state.get("persons_involved", 1)))
    # proposed_number_of_people = int(parse_float(state.get("proposed_number_of_people", 0)))
    # derived["number_of_persons_involved_currently"] = persons_involved
    # derived["proposed_number_of_persons_involved"] = persons_involved + proposed_number_of_people

    # current_wages_monthly = parse_float(state.get("current_wages"))
    # proposed_wages_monthly = parse_float(state.get("proposed_wages"))
    # derived["current_total_wages"] = round_to_500(current_wages_monthly * 12)
    # derived["proposed_total_wages"] = round_to_500(12 * (proposed_wages_monthly + current_wages_monthly))

    # if persons_involved == 0:
    #     derived["current_total_wages"] = "no person involved"
    # if (persons_involved + proposed_number_of_people) == 0:
    #     derived["proposed_total_wages"] = "no person involved"

    # if is_grocery_type:
    #     cycle_months = 1
    # elif "poultry" in business_type:
    #     cycle_months = 2
    # elif "goatory" in business_type or "goatry" in business_type:
    #     cycle_months = 8
    # elif "dairy" in business_type:
    #     cycle_months = 6
    # elif any(t in business_type for t in ["tailor", "electrician", "electric"]):
    #     cycle_months = 2
    # else:
    #     cycle_months = 2
    # derived["working_cycle_months"] = cycle_months

    # input_inventory = parse_float(state.get("calculated_inventory") or state.get("inventory"))
    # if input_inventory > 0:
    #     base_inventory = input_inventory
    # else:
    #     revenue_ratio = (clamped_proposed_rev * 12 / (monthly_rev * 12)) if monthly_rev > 0 else 1.0
    #     base_inventory = parse_float(state.get("inventory_amount")) * revenue_ratio

    # inv_multiplier = base_inventory / clamped_proposed_rev if clamped_proposed_rev > 0 else 0.0
    # if 3.0 <= inv_multiplier <= 4.0:
    #     inventory_amount = int(round(base_inventory))
    # else:
    #     inventory_amount = int(round(random_in_range(3.0, 4.0) * clamped_proposed_rev))

    # derived["inventory"] = round_to_500(inventory_amount)
    # derived["debtors"] = round_to_500(parse_float(state.get("debtors_amount") or state.get("debtors")))
    # derived["creditors"] = round_to_500(parse_float(state.get("creditors_amount") or state.get("creditors")))

    # working_gap = derived["inventory"] + derived["debtors"] - derived["creditors"]
    # derived["promoters_contribution_in_working_capital"] = round_to_500(working_gap * 0.25)
    # derived["limits"] = round_to_500(working_gap - derived["promoters_contribution_in_working_capital"])
    # derived["cash_credit_amount"] = round_to_500(working_gap)
    # derived["cash_credit_purpose"] = "Inventory Management"

    # machine_cost = parse_float(state.get("machine_cost") or state.get("approximate_cost"))
    # machine_name = state.get("machine_name") or state.get("type_of_machine_equipment") or "No Machine purchase"

    # if machine_cost > 0:
    #     derived["term_loan_required"] = round_to_500(machine_cost * 0.90)
    #     derived["promotors_contribution_in_term_loan"] = round_to_500(machine_cost * 0.25)
    #     derived["term_loan_purpose"] = f"for buying {machine_name}"
    #     derived["type_of_machine_equipment"] = machine_name
    #     derived["purpose"] = state.get("machine_purpose") or state.get("purpose") or "not applicable as no machine purchase"
    #     derived["name_of_supplier"] = state.get("machine_supplier") or state.get("name_of_supplier") or "not applicable as no machine purchase"
    #     derived["approximate_cost"] = round_to_500(machine_cost)
    #     derived["repayment_period_requested_for"] = "5"
    #     derived["morotorium_period"] = "Not Needed"
    # else:
    #     derived["term_loan_required"] = 0
    #     derived["promotors_contribution_in_term_loan"] = 0
    #     derived["term_loan_purpose"] = "not applicable as no machine purchase"
    #     derived["type_of_machine_equipment"] = "No Machine purchase"
    #     derived["purpose"] = "not applicable as no machine purchase"
    #     derived["name_of_supplier"] = "not applicable as no machine purchase"
    #     derived["approximate_cost"] = 0
    #     derived["repayment_period_requested_for"] = "5"
    #     derived["morotorium_period"] = "Not Needed"

    # total_loan = derived["term_loan_required"] + derived["cash_credit_amount"]
    # requested_loan = parse_float(state.get("loan_required") or state.get("loan_amount"))
    # if requested_loan > 0 and total_loan > requested_loan:
    #     total_loan = requested_loan

    # derived["total_loan_required_amount"] = round_to_500(total_loan)

    # co_borrower = state.get("co_borrower", "No")
    # if str(co_borrower).lower() in ["yes", "true", "y"]:
    #     derived["co_borrower"] = "Coborrower is present and the corresponding relevant documents are in place"
    # else:
    #     derived["co_borrower"] = "Coborrower is not present"

    # if not is_livestock:
    #     derived["shade_location"] = "NA"
    #     derived["shade_owned_or_rented"] = "NA"
    # else:
    #     derived["shade_location"] = state.get("shade_location", "NA")
    #     derived["shade_owned_or_rented"] = state.get("shade_owned_or_rented", "NA")

    # derived["constitution"] = "Proprietary"
    # derived["unit_is_registered"] = "Yes"
    # derived["skill_certified"] = "yes (Self Trained)"

    # return derived
