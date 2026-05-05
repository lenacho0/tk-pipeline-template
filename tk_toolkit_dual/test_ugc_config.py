import unittest

from ugc_config import UGC_BASE_TOKEN, load_ugc_table_ids


class UGCConfigTest(unittest.TestCase):
    def test_load_ugc_table_ids_from_docs_snapshot(self):
        table_ids = load_ugc_table_ids()
        self.assertEqual(UGC_BASE_TOKEN, "LBWUbgRfEavAgjsXNIhcpo0Dnvb")
        self.assertEqual(table_ids["ugc_01_analysis"], "tblSPpWWOrnOzHSq")
        self.assertEqual(table_ids["ugc_02_script_batch"], "tblbLHA2DyIwZHfF")
        self.assertEqual(table_ids["ugc_03_script_version"], "tblgDc6nuk6UWkLH")


if __name__ == "__main__":
    unittest.main()
