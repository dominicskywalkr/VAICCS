import unittest
import main as mainmod

class TestBleepText(unittest.TestCase):
    def setUp(self):
        # ensure starting from default
        mainmod.BLEEP_SETTINGS = {'mode':'fixed','mask_char':'*','custom_text':'****'}
        self.bad = {'badword', 'mother-in-law', "o'connor"}

    def test_fixed_replacement(self):
        mainmod.BLEEP_SETTINGS = {'mode':'fixed','custom_text':'[BLEEP]','mask_char':'*'}
        out = mainmod.bleep_text('hello BADWORD!', bad_set=self.bad)
        self.assertEqual(out, 'hello [BLEEP]!')

    def test_keep_first(self):
        mainmod.BLEEP_SETTINGS = {'mode':'keep_first','mask_char':'*','custom_text':'****'}
        out = mainmod.bleep_text('badword', bad_set=self.bad)
        self.assertTrue(out.startswith('b'))
        self.assertIn('*', out)
        self.assertEqual(len(out), len('badword'))

    def test_keep_last(self):
        mainmod.BLEEP_SETTINGS = {'mode':'keep_last','mask_char':'#','custom_text':'****'}
        out = mainmod.bleep_text('badword', bad_set=self.bad)
        self.assertTrue(out.endswith('d'))
        self.assertIn('#', out)
        self.assertEqual(len(out), len('badword'))

    def test_keep_first_last_hyphen(self):
        mainmod.BLEEP_SETTINGS = {'mode':'keep_first_last','mask_char':'*','custom_text':'****'}
        out = mainmod.bleep_text('mother-in-law', bad_set=self.bad)
        # should preserve hyphens
        self.assertIn('-', out)
        # first and last alnum chars should be preserved
        self.assertTrue(out.strip().startswith('m'))
        # length should match original
        self.assertEqual(len(out), len('mother-in-law'))

    def test_remove(self):
        mainmod.BLEEP_SETTINGS = {'mode':'remove','mask_char':'*','custom_text':''}
        out = mainmod.bleep_text('say badword now', bad_set=self.bad)
        # badword removed, spaces preserved -> two spaces may collapse; ensure 'badword' not present
        self.assertNotIn('badword', out.lower())

    def test_custom_text(self):
        mainmod.BLEEP_SETTINGS = {'mode':'fixed','custom_text':'[X]','mask_char':'*'}
        out = mainmod.bleep_text("o'connor is here", bad_set=self.bad)
        self.assertIn('[X]', out)

if __name__ == '__main__':
    unittest.main()
