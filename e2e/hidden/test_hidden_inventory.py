"""Hidden acceptance tests for SPEC.md (copied in after the run; the agents never see them)."""
import unittest

from inventory import Inventory, InventoryError


class Hidden(unittest.TestCase):
    def setUp(self):
        self.inv = Inventory()
        self.inv.add("a", 10)

    def test_reserve_release_commit(self):
        r1 = self.inv.reserve("a", 4)
        r2 = self.inv.reserve("a", 6)
        self.assertNotEqual(r1, r2)
        self.assertEqual(self.inv.available("a"), 0)
        with self.assertRaises(InventoryError):
            self.inv.reserve("a", 1)
        self.inv.release(r1)
        self.assertEqual(self.inv.available("a"), 4)
        self.inv.commit(r2)
        self.assertEqual((self.inv.stock("a"), self.inv.available("a")), (4, 4))
        for rid in (r1, r2, "nope"):
            with self.assertRaises(InventoryError):
                self.inv.release(rid)
            with self.assertRaises(InventoryError):
                self.inv.commit(rid)

    def test_remove_respects_reservations(self):
        self.inv.reserve("a", 7)
        with self.assertRaises(InventoryError):
            self.inv.remove("a", 4)
        self.assertEqual(self.inv.stock("a"), 10)
        self.inv.remove("a", 3)
        self.assertEqual((self.inv.stock("a"), self.inv.available("a")), (7, 0))

    def test_bad_input_leaves_state_unchanged(self):
        for qty in (0, -1, 1.5, True, "2"):
            with self.assertRaises(InventoryError):
                self.inv.add("a", qty)
            with self.assertRaises(InventoryError):
                self.inv.reserve("a", qty)
        with self.assertRaises(InventoryError):
            self.inv.remove("ghost", 1)
        with self.assertRaises(InventoryError):
            self.inv.reserve("ghost", 1)
        with self.assertRaises(InventoryError):
            self.inv.remove("a", 11)
        self.assertEqual((self.inv.stock("a"), self.inv.available("a")), (10, 10))
        self.assertEqual((self.inv.stock("ghost"), self.inv.available("ghost")), (0, 0))
        self.assertTrue(issubclass(InventoryError, ValueError))
