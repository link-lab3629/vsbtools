import unittest
from unittest.mock import ANY, patch

import numpy as np

from vsbtools.materials_dataset.analysis.guidance_statistics import histo_data_collection


class HistogramDataCollectionTest(unittest.TestCase):
    @patch("vsbtools.materials_dataset.analysis.guidance_statistics.calculate_values")
    def test_forwards_filter_max_el(self, calculate_values):
        calculate_values.return_value = {"Non-guided": np.array([0.5, 1.0, 1.5])}

        histograms = histo_data_collection(
            {"Non-guided": object()},
            callable_name="compute_mean_coordination",
            callable_params={"type_A": 6, "type_B": 6},
            filter_max_el=False,
        )

        calculate_values.assert_called_once_with(
            {"Non-guided": ANY},
            "compute_mean_coordination",
            callable_params={"type_A": 6, "type_B": 6},
            fn=None,
            filter_max_el=False,
            force_gpu=0,
        )
        self.assertEqual(histograms[0]["label"], "Non-guided")
        self.assertAlmostEqual(float(histograms[0]["counts"].sum()), 1.0)

    @patch("vsbtools.materials_dataset.analysis.guidance_statistics.calculate_values")
    def test_accepts_an_existing_callable(self, calculate_values):
        calculate_values.return_value = {"guided": np.array([1.0, 2.0, 3.0])}
        descriptor = lambda entry: entry

        histograms = histo_data_collection(
            {"guided": object()},
            fn=descriptor,
            filter_max_el=False,
        )

        calculate_values.assert_called_once_with(
            {"guided": ANY},
            None,
            callable_params=None,
            fn=descriptor,
            filter_max_el=False,
            force_gpu=0,
        )
        self.assertEqual(histograms[0]["label"], "guided")
        self.assertAlmostEqual(float(histograms[0]["counts"].sum()), 1.0)


if __name__ == "__main__":
    unittest.main()
