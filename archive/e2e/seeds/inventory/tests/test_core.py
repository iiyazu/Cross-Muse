import unittest

from inventory import Inventory


class TestInventory(unittest.TestCase):
    def test_add_remove(self):
        inv = Inventory()
        inv.add("apple", 5)
        inv.remove("apple", 2)
        self.assertEqual(inv.stock("apple"), 3)


if __name__ == "__main__":
    unittest.main()
