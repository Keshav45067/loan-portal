import sys
import unittest
sys.path.append('app-orchestrator')
sys.path.append('.')
from shared.shared_config_loader import load_resolved_scheme_config
from calculations import calculate_derived_fields

class TestYAMLCalculations(unittest.TestCase):
    def setUp(self):
        self.config = load_resolved_scheme_config('base-mudra')
        self.test_state = {
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

    def test_yaml_derived_calculations(self):
        derived = calculate_derived_fields(self.test_state, scheme_config=self.config)
        self.assertEqual(derived['experience_in_line_of_activity'], 7)
        self.assertEqual(derived['net_sales_present_year'], 600000)
        self.assertEqual(derived['working_cycle_months'], 6)
        self.assertEqual(derived['term_loan_required'], 180000)
        self.assertEqual(derived['promotors_contribution_in_term_loan'], 50000)
        self.assertEqual(derived['shade_location'], 'Village Rampur')
        self.assertEqual(derived['constitution'], 'Proprietary')

if __name__ == '__main__':
    unittest.main()
