import math
import random
from datetime import datetime

def parse_float(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

def round_to_500(val: float) -> int:
    return int(round(val / 500.0) * 500)

def random_in_range(min_val: float, max_val: float) -> float:
    return random.uniform(min_val, max_val)

def calculate_derived_fields(state: dict) -> dict:
    derived = {}
    
    # 1. Experience years
    commencement_date = state.get("date_of_commencement")
    if commencement_date:
        try:
            if "-" in str(commencement_date):
                comm_year = datetime.strptime(str(commencement_date).split("T")[0], "%Y-%m-%d").year
            else:
                comm_year = int(commencement_date)
            current_year = datetime.now().year
            derived["experience_in_line_of_activity"] = max(0, current_year - comm_year + 1)
        except Exception:
            derived["experience_in_line_of_activity"] = 1
    else:
         derived["experience_in_line_of_activity"] = 1

    business_type = str(state.get("business_type", "other")).lower()
    is_livestock = any(t in business_type for t in ["goatory", "poultry", "dairy", "goatry"])
    is_grocery_type = any(t in business_type for t in ["grocery", "stationary", "clothing"])

    # 2. Sales Projections
    monthly_rev = parse_float(state.get("monthly_revenue"))
    derived["net_sales_present_year"] = round_to_500(monthly_rev * 12)

    # 3. Proposed Sales
    raw_proposed_rev = parse_float(state.get("proposed_monthly_revenue"))
    growth_ratio = (raw_proposed_rev / monthly_rev) if monthly_rev > 0 else 1.0
    
    if growth_ratio < 1.1 or growth_ratio > 1.2:
        clamped_proposed_rev = random_in_range(1.1, 1.2) * monthly_rev
    else:
        clamped_proposed_rev = raw_proposed_rev

    derived["net_sales_next_year"] = round_to_500(clamped_proposed_rev * 12)
    derived["proposed_monthly_revenue"] = clamped_proposed_rev

    # 4. Past year sales
    last_year_monthly_rev = parse_float(state.get("last_year_monthly_revenue"))
    past_growth = (monthly_rev / last_year_monthly_rev) if last_year_monthly_rev > 0 else 1.0
    
    if past_growth < 1.05 or past_growth > 1.15:
        adjusted_last_year_monthly_rev = random_in_range(0.85, 0.95) * monthly_rev
    else:
        adjusted_last_year_monthly_rev = last_year_monthly_rev
        
    derived["net_sales_past_year_1"] = round_to_500(adjusted_last_year_monthly_rev * 12)
    derived["net_sales_past_year_2"] = round_to_500(random_in_range(0.85, 0.95) * adjusted_last_year_monthly_rev * 12)

    # 5. Profit Projections
    raw_monthly_profit = parse_float(state.get("monthly_profit"))
    profit_margin = (raw_monthly_profit / monthly_rev) if monthly_rev > 0 else 0.5
    if profit_margin < 0.40 or profit_margin > 0.60:
        profit_margin = random_in_range(0.40, 0.60)
        
    actual_monthly_profit = profit_margin * monthly_rev
    derived["net_profit_present_year"] = round_to_500(actual_monthly_profit * 12)
    derived["net_profit_past_year_1"] = round_to_500(profit_margin * adjusted_last_year_monthly_rev * 12)
    derived["net_profit_past_year_2"] = round_to_500(profit_margin * random_in_range(0.85, 0.95) * adjusted_last_year_monthly_rev * 12)
    derived["net_profit_next_year"] = round_to_500(profit_margin * clamped_proposed_rev * 12)

    # 6. Wages and Employees
    persons_involved = int(parse_float(state.get("persons_involved", 1)))
    proposed_number_of_people = int(parse_float(state.get("proposed_number_of_people", 0)))
    
    derived["number_of_persons_involved_currently"] = persons_involved
    derived["proposed_number_of_persons_involved"] = persons_involved + proposed_number_of_people

    current_wages_monthly = parse_float(state.get("current_wages"))
    proposed_wages_monthly = parse_float(state.get("proposed_wages"))
    
    derived["current_total_wages"] = round_to_500(current_wages_monthly * 12)
    derived["proposed_total_wages"] = round_to_500(12 * (proposed_wages_monthly + current_wages_monthly))

    if persons_involved == 0:
        derived["current_total_wages"] = "no person involved"
    if (persons_involved + proposed_number_of_people) == 0:
        derived["proposed_total_wages"] = "no person involved"

    # 7. Working cycle months
    if is_grocery_type:
        cycle_months = 1
    elif "poultry" in business_type:
        cycle_months = 2
    elif "goatory" in business_type or "goatry" in business_type:
        cycle_months = 8
    elif "dairy" in business_type:
        cycle_months = 6
    elif any(t in business_type for t in ["tailor", "electrician", "electric"]):
        cycle_months = 2
    else:
        cycle_months = 2
    derived["working_cycle_months"] = cycle_months

    # 8. Working Capital / Inventory
    input_inventory = parse_float(state.get("calculated_inventory") or state.get("inventory"))
    if input_inventory > 0:
        base_inventory = input_inventory
    else:
        revenue_ratio = (clamped_proposed_rev * 12 / (monthly_rev * 12)) if monthly_rev > 0 else 1.0
        base_inventory = parse_float(state.get("inventory_amount")) * revenue_ratio

    inv_multiplier = base_inventory / clamped_proposed_rev if clamped_proposed_rev > 0 else 0.0
    if 3.0 <= inv_multiplier <= 4.0:
        inventory_amount = int(round(base_inventory))
    else:
        inventory_amount = int(round(random_in_range(3.0, 4.0) * clamped_proposed_rev))
        
    derived["inventory"] = round_to_500(inventory_amount)
    
    # Debtors / Creditors
    derived["debtors"] = round_to_500(parse_float(state.get("debtors_amount") or state.get("debtors")))
    derived["creditors"] = round_to_500(parse_float(state.get("creditors_amount") or state.get("creditors")))

    # Promoter Contribution (WC) & CC Limits
    working_gap = derived["inventory"] + derived["debtors"] - derived["creditors"]
    derived["promoters_contribution_in_working_capital"] = round_to_500(working_gap * 0.25)
    derived["limits"] = round_to_500(working_gap - derived["promoters_contribution_in_working_capital"])
    derived["cash_credit_amount"] = round_to_500(working_gap)
    derived["cash_credit_purpose"] = "Inventory Management"

    # 9. Term Loan
    machine_cost = parse_float(state.get("machine_cost") or state.get("approximate_cost"))
    machine_name = state.get("machine_name") or state.get("type_of_machine_equipment") or "No Machine purchase"
    
    if machine_cost > 0:
        derived["term_loan_required"] = round_to_500(machine_cost * 0.90)
        derived["promotors_contribution_in_term_loan"] = round_to_500(machine_cost * 0.25)
        derived["term_loan_purpose"] = f"for buying {machine_name}"
        derived["type_of_machine_equipment"] = machine_name
        derived["purpose"] = state.get("machine_purpose") or state.get("purpose") or "not applicable as no machine purchase"
        derived["name_of_supplier"] = state.get("machine_supplier") or state.get("name_of_supplier") or "not applicable as no machine purchase"
        derived["approximate_cost"] = round_to_500(machine_cost)
        derived["repayment_period_requested_for"] = "5"
        derived["morotorium_period"] = "Not Needed"
    else:
        derived["term_loan_required"] = 0
        derived["promotors_contribution_in_term_loan"] = 0
        derived["term_loan_purpose"] = "not applicable as no machine purchase"
        derived["type_of_machine_equipment"] = "No Machine purchase"
        derived["purpose"] = "not applicable as no machine purchase"
        derived["name_of_supplier"] = "not applicable as no machine purchase"
        derived["approximate_cost"] = 0
        derived["repayment_period_requested_for"] = "5"
        derived["morotorium_period"] = "Not Needed"

    # 10. Total Loan
    total_loan = derived["term_loan_required"] + derived["cash_credit_amount"]
    
    requested_loan = parse_float(state.get("loan_required") or state.get("loan_amount"))
    if requested_loan > 0 and total_loan > requested_loan:
        total_loan = requested_loan
        
    derived["total_loan_required_amount"] = round_to_500(total_loan)

    # 11. Co-borrower
    co_borrower = state.get("co_borrower", "No")
    if str(co_borrower).lower() in ["yes", "true", "y"]:
        derived["co_borrower"] = "Coborrower is present and the corresponding relevant documents are in place"
    else:
        derived["co_borrower"] = "Coborrower is not present"

    # 12. Livestock specific fields
    if not is_livestock:
        derived["shade_location"] = "NA"
        derived["shade_owned_or_rented"] = "NA"
    else:
        derived["shade_location"] = state.get("shade_location", "NA")
        derived["shade_owned_or_rented"] = state.get("shade_owned_or_rented", "NA")

    # 13. Static values / general
    derived["constitution"] = "Proprietary"
    derived["unit_is_registered"] = "Yes"
    derived["skill_certified"] = "yes (Self Trained)"

    return derived
