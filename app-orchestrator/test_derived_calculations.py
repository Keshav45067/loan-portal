import sys
import unittest
sys.path.append('app-orchestrator')
sys.path.append('.')
from shared.shared_config_loader import load_resolved_scheme_config
from calculations import calculate_derived_fields

class TestYAMLCalculations(unittest.TestCase):
    def setUp(self):
        self.config = load_resolved_scheme_config('base-mudra')
        self.test_state_numeric = {
            'date_of_commencement': '2020-05-15',
            'business_type': 'dairy farm',
            'monthly_revenue': 50000,
            'proposed_monthly_revenue': 60000,
            'monthly_profit': 25000,
            'persons_involved': 2,
            'proposed_number_of_people': 1,
            'current_wages': 15000,
            'proposed_wages': 5000,
            'inventory_amount': 150000,
            'debtors': 20000,
            'creditors': 10000,
            'machine_cost': 200000,
            'machine_name': 'Milking Machine',
            'loan_required': 300000,
            'co_borrower': 'yes',
            'shade_location': 'Village Rampur',
            'shade_owned_or_rented': 'Owned'
        }

        # Simulating string-encoded extractions from voice interview
        self.test_state_string = {
            'date_of_commencement': '2017-06-20',
            'business_type': 'trading',
            'monthly_revenue': '12500',
            'monthly_profit': '5000',
            'last_year_monthly_revenue': '5000',
            'persons_involved': '1',
            'proposed_number_of_people': 0,
            'current_wages': '0',
            'proposed_wages': '0',
            'inventory_amount': '20000',
            'debtors_amount': '2500',
            'creditors_amount': '12000',
            'machine_cost': '2000',
            'machine_name': 'Welding machine',
            'machine_purpose': 'Welding for greeting cards',
            'machine_supplier': 'Local Market',
            'co_borrower': 'No',
        }

    def _assert_no_raw_formulas_or_astronomical_values(self, derived, context_name=""):
        for k, v in derived.items():
            if isinstance(v, str):
                self.assertFalse('round_to(' in v, f'[{context_name}] Field {k} contains raw formula: {v}')
                self.assertFalse('if_' in v, f'[{context_name}] Field {k} contains raw formula: {v}')
                self.assertFalse('clamp_' in v, f'[{context_name}] Field {k} contains raw formula: {v}')
                self.assertFalse('years_since(' in v, f'[{context_name}] Field {k} contains raw formula: {v}')
            if isinstance(v, (int, float)):
                self.assertLess(v, 10**12, f'[{context_name}] Field {k} has astronomical number: {v}')

    def test_numeric_derived_calculations(self):
        derived = calculate_derived_fields(self.test_state_numeric, scheme_config=self.config)
        self.assertGreaterEqual(derived['experience_in_line_of_activity'], 1)
        self.assertEqual(derived['net_sales_present_year'], 600000)
        self.assertEqual(derived['working_cycle_months'], 6)
        self.assertEqual(derived['term_loan_required'], 180000)
        self.assertEqual(derived['promotors_contribution_in_term_loan'], 50000)
        self.assertEqual(derived['shade_location'], 'Village Rampur')
        self.assertEqual(derived['constitution'], 'Proprietary')
        self._assert_no_raw_formulas_or_astronomical_values(derived, "numeric")

    def test_string_encoded_voice_extractions(self):
        derived = calculate_derived_fields(self.test_state_string, scheme_config=self.config)
        self.assertEqual(derived['net_sales_present_year'], 150000)
        self.assertEqual(derived['net_profit_present_year'], 60000)
        self.assertEqual(derived['term_loan_required'], 2000)
        self.assertEqual(derived['promotors_contribution_in_term_loan'], 500)
        self.assertIsInstance(derived['total_loan_required_amount'], (int, float))
        self.assertGreater(derived['total_loan_required_amount'], 0)
        self.assertEqual(derived['proposed_total_wages'], 0)
        self.assertEqual(derived['current_total_wages'], 0)
        self.assertEqual(derived['co_borrower'], 'Coborrower is not present')
        self.assertEqual(derived['constitution'], 'Proprietary')
        self._assert_no_raw_formulas_or_astronomical_values(derived, "string_encoded")

    def test_empty_and_missing_context(self):
        derived = calculate_derived_fields({}, scheme_config=self.config)
        self.assertEqual(derived['net_sales_present_year'], 0)
        self.assertEqual(derived['net_profit_present_year'], 0)
        self.assertEqual(derived['term_loan_required'], 0)
        self.assertEqual(derived['promotors_contribution_in_term_loan'], 0)
        self.assertEqual(derived['co_borrower'], 'Coborrower is not present')
        self._assert_no_raw_formulas_or_astronomical_values(derived, "empty_context")

    def test_all_none_and_empty_strings(self):
        state_none = {k: None for k in self.test_state_numeric.keys()}
        derived_none = calculate_derived_fields(state_none, scheme_config=self.config)
        self._assert_no_raw_formulas_or_astronomical_values(derived_none, "all_none")

        state_empty = {k: "" for k in self.test_state_numeric.keys()}
        derived_empty = calculate_derived_fields(state_empty, scheme_config=self.config)
        self._assert_no_raw_formulas_or_astronomical_values(derived_empty, "all_empty")

    def test_all_zeros_numeric_and_string(self):
        state_zero_num = {k: 0 for k in ['monthly_revenue', 'monthly_profit', 'current_wages', 'machine_cost', 'inventory_amount']}
        derived_zero_num = calculate_derived_fields(state_zero_num, scheme_config=self.config)
        self.assertEqual(derived_zero_num['net_sales_present_year'], 0)
        self._assert_no_raw_formulas_or_astronomical_values(derived_zero_num, "zero_numeric")

        state_zero_str = {k: '0' for k in ['monthly_revenue', 'monthly_profit', 'current_wages', 'machine_cost', 'inventory_amount']}
        derived_zero_str = calculate_derived_fields(state_zero_str, scheme_config=self.config)
        self.assertEqual(derived_zero_str['net_sales_present_year'], 0)
        self._assert_no_raw_formulas_or_astronomical_values(derived_zero_str, "zero_string")

    def test_corrupted_tokens_and_invalid_data(self):
        state_corrupt = {
            'monthly_revenue': 'null',
            'monthly_profit': 'None',
            'machine_cost': 'NA',
            'date_of_commencement': 'invalid-date-format',
            'persons_involved': 'undefined',
            'current_wages': 'N/A',
            'co_borrower': 'False',
        }
        derived = calculate_derived_fields(state_corrupt, scheme_config=self.config)
        self.assertEqual(derived['net_sales_present_year'], 0)
        self.assertEqual(derived['term_loan_required'], 0)
        self.assertEqual(derived['co_borrower'], 'Coborrower is not present')
        self._assert_no_raw_formulas_or_astronomical_values(derived, "corrupted_tokens")

    def test_negative_numbers_and_divisions(self):
        state_negative = {
            'monthly_revenue': -10000,
            'monthly_profit': -5000,
            'machine_cost': -2000,
            'inventory_amount': -50000,
        }
        derived = calculate_derived_fields(state_negative, scheme_config=self.config)
        self._assert_no_raw_formulas_or_astronomical_values(derived, "negative_numbers")

    def test_business_types_and_coborrower_permutations(self):
        for b_type, expected_cycle in [('dairy', 6), ('grocery', 1), ('poultry', 2), ('clothing', 1), ('tailor', 2), ('other', 2)]:
            derived = calculate_derived_fields({'business_type': b_type}, scheme_config=self.config)
            self.assertEqual(derived['working_cycle_months'], expected_cycle)

        for cb_val, is_present in [('Yes', True), ('yes', True), (True, True), ('1', True), ('हाँ', True),
                                   ('No', False), ('no', False), (False, False), ('0', False), (None, False), ('', False), ('NA', False)]:
            derived = calculate_derived_fields({'co_borrower': cb_val}, scheme_config=self.config)
            expected_msg = 'Coborrower is present and the corresponding relevant documents are in place' if is_present else 'Coborrower is not present'
            self.assertEqual(derived['co_borrower'], expected_msg, f'Failed for co_borrower={cb_val}')

if __name__ == '__main__':
    unittest.main()
