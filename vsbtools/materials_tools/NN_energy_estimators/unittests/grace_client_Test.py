import unittest
from unittest.mock import patch

from .. import grace_client


class GraceClientModel_Test(unittest.TestCase):
    def test_explicit_model_is_exported_to_helper_environment(self):
        env = grace_client._helper_env(
            force_gpu=2,
            grace_model="GRACE-3L-OMAT-large-ft-AM",
        )

        self.assertEqual(env["VSB_GRACE_MODEL"], "GRACE-3L-OMAT-large-ft-AM")
        self.assertEqual(env["VSB_FORCE_GPU_INDEX"], "2")

    def test_default_model_is_backward_compatible(self):
        with patch.dict(grace_client.os.environ, {}, clear=True):
            self.assertEqual(
                grace_client.resolve_grace_model(),
                "GRACE-2L-OMAT-large-ft-AM",
            )

    def test_model_name_is_validated(self):
        with self.assertRaises(ValueError):
            grace_client.resolve_grace_model("  ")
        with self.assertRaises(TypeError):
            grace_client.resolve_grace_model(3)


if __name__ == "__main__":
    unittest.main()
