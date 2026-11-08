"""Numerical invariants demonstrated by the native pilot's partial failures."""
import unittest
import numpy as np
from review_so_results import integrate_valid,native_validity


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.t=np.array([1.,1.01,1.02])
        self.a=np.full((3,2),.2);self.f=np.ones((3,2))
        self.log='\n'.join(f'time = {t} Performance = 1 Constraint violation = 1e-9' for t in self.t)

    def test_native_failure_rejected_even_with_finite_storage(self):
        log=self.log+'\nOPTIMIZATION FAILED...\nThe optimizer could not find a solution at time = 1.01.'
        reasons,_=native_validity(self.t,self.a,self.f,log,1e-4)
        self.assertFalse(reasons[0]);self.assertIn('native_optimizer_failure',reasons[1]);self.assertFalse(reasons[2])

    def test_large_constraint_violation_rejected_without_failure_banner(self):
        log=self.log.replace('time = 1.01 Performance = 1 Constraint violation = 1e-9','time = 1.01 Performance = 1 Constraint violation = 3.2')
        reasons,_=native_validity(self.t,self.a,self.f,log,1e-4)
        self.assertIn('constraint_violation',reasons[1])

    def test_integral_never_bridges_failed_sample(self):
        self.assertIsNone(integrate_valid(self.t,np.ones(3),np.array([True,False,True])))
        self.assertAlmostEqual(integrate_valid(self.t,np.ones(3),np.array([True,True,False])),.01)

    def test_missing_native_record_and_nonfinite_values_rejected(self):
        self.a[1,0]=np.nan
        reasons,_=native_validity(self.t,self.a,self.f,self.log.splitlines()[0],1e-4)
        self.assertIn('nonfinite_output',reasons[1]);self.assertIn('native_constraint_record_missing',reasons[2])


if __name__=='__main__':unittest.main()
