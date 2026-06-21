# Mapping: FIELD_MAP label (snake_cased) -> mudra_user_data column.
FIELD_TO_DB_MAP = {
    # A. Applicant Information
    "name_of_the_applicant":                       "applicant_name",

    # B. Business Information
    "enterprise_name":                             "enterprise_name",
    "constitution":                                "constitution",
    "current_business_address":                    "current_business_address",
    "district":                                    "district",
    "state":                                       "state",
    "pin_code":                                    "pin_code",
    "type_of_business":                            "business_type",
    "mobile_number":                               "mobile_number",
    "email":                                       "email",
    "existing_business_activity":                  "existing_business_activity",
    "proposed_business_activity":                  "proposed_business_activity",
    "date_of_commencement":                        "date_of_commencement",
    "unit_is_registered":                          "unit_is_registered",
    "registration_number_of_business":             "registration_number_of_business",
    "registered_office_address":                   "registered_office_address",
    "skill_certified":                             "skill_certified",
    "social_category_sc_st_obc_minority":          "social_category",
    "if_minority_religion":                        "minority_religion",

    # C. Background Information of Proprietor
    "date_of_birth":                               "date_of_birth",
    "gender":                                      "gender",
    "resident_address":                            "resident_address",
    "academic_qualification":                      "academic_qualification",
    "experience_in_line_of_the_activity":          "experience_in_line_of_activity",
    "id_proof":                                    "id_proof",
    "id_proof_number":                             "id_proof_number",
    "address_proof":                               "address_proof",
    "address_proof_number":                        "address_proof_number",
    "pan_card_number":                             "pan_card_number",

    # E. Banking / Credit Facilities
    "presently_banking_with":                      "presently_banking_with",
    "saving_bank_account_number":                  "saving_bank_account_number",
    "ifsc_code_of_saving_bank_account_branch":     "ifsc_code_of_saving_bank_account_branch",
    "existing_loan":                               "existing_loan",
    "existing_loan_emi":                           "existing_loan_emi",
    "existing_loan_lender":                        "existing_loan_lender",
    "existing_loan_outstanding":                   "existing_loan_outstanding",
    "previous_loan_default":                       "previous_loan_default",
    "default_reason":                              "default_reason",

    # F. Credit Facilities Proposed
    "cash_credit_amount":                          "cash_credit_amount",
    "cash_credit_purpose":                         "cash_credit_purpose",
    "term_loan_purpose":                           "term_loan_purpose",

    # G. Working Capital
    "number_of_persons_involved_currently":        "number_of_persons_involved_currently",
    "proposed_number_of_persons_involved":         "proposed_number_of_persons_involved",
    "current_total_wages":                         "current_total_wages",
    "proposed_total_wages":                        "proposed_total_wages",
    "inventory":                                   "inventory",
    "debtors":                                     "debtors",
    "creditors":                                   "creditors",
    "promoter_s_contribution_in_working_capital":  "promoters_contribution_in_working_capital",
    "limits":                                      "limits",

    # H. Term Loan Requirements
    "type_of_machine_equipment":                   "type_of_machine_equipment",
    "purpose":                                     "purpose",
    "name_of_supplier":                            "name_of_supplier",
    "approximate_cost":                            "approximate_cost",
    "promotor_s_contribution_in_term_loan":        "promotors_contribution_in_term_loan",
    "term_loan_required":                          "term_loan_required",
    "repayment_period_requested_for":              "repayment_period_requested_for",
    "morotorium_period":                           "morotorium_period",

    # I. Past Performance / Future Estimates
    "net_sales_past_year_ii":                      "net_sales_past_year_2",
    "net_sales_past_year_i":                       "net_sales_past_year_1",
    "net_sales_present_year":                      "net_sales_present_year",
    "net_sales_next_year":                         "net_sales_next_year",
    "net_profit_past_year_ii":                     "net_profit_past_year_2",
    "net_profit_past_year_i":                      "net_profit_past_year_1",
    "net_profit_present_year":                     "net_profit_present_year",
    "net_profit_next_year":                        "net_profit_next_year",

    # J. Total Loan Required
    "total_loan_required":                         "total_loan_required_amount",

    # K. Family Information
    "number_of_family_members":                    "number_of_family_members",
    "marital_status":                              "marital_status",
    "number_of_kids":                              "number_of_kids",
    "co_borrower":                                 "co_borrower",

    # L. Raw Interview Data
    "proposed_monthly_revenue":                    "proposed_monthly_revenue",

    # M. Livestock-Specific
    "shade_location":                              "shade_location",
    "shade_owned_or_rented":                       "shade_owned_or_rented",

    # N. QA & Documentation Stage mappings
    "business_purpose":                            "proposed_business_activity",
    "is_married":                                  "is_married",
    "spouse_mobile":                               "spouse_phone",
    "spouse_phone":                                "spouse_phone",
    "spouse_pan_number":                           "spouse_pan_card_number",
    "spouse_pan_card_number":                      "spouse_pan_card_number",
    "documentation_stage":                         "documentation_stage",
}
