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

    def test_numeric_derived_calculations(self):
        derived = calculate_derived_fields(self.test_state_numeric, scheme_config=self.config)
        self.assertGreaterEqual(derived['experience_in_line_of_activity'], 1)
        self.assertEqual(derived['net_sales_present_year'], 600000)
        self.assertEqual(derived['working_cycle_months'], 6)
        self.assertEqual(derived['term_loan_required'], 180000)
        self.assertEqual(derived['promotors_contribution_in_term_loan'], 50000)
        self.assertEqual(derived['shade_location'], 'Village Rampur')
        self.assertEqual(derived['constitution'], 'Proprietary')

    def test_string_encoded_voice_extractions(self):
        derived = calculate_derived_fields(self.test_state_string, scheme_config=self.config)
        
        # Verify no string multiplication bugs (e.g. 60-digit numbers)
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

        # Assert no derived field contains raw un-evaluated python formulas
        for k, v in derived.items():
            if isinstance(v, str):
                self.assertFalse('round_to(' in v, f'Field {k} contains raw round_to formula: {v}')
                self.assertFalse('if_' in v, f'Field {k} contains raw if_ formula: {v}')

if __name__ == '__main__':
    unittest.main()
