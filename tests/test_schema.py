import unittest

from xcube.util.jsonschema import JsonObjectSchema
from xcube_smos.schema import STORE_PARAMS_SCHEMA
from xcube_smos.schema import OPEN_PARAMS_SCHEMA


class SmosSchemaTest(unittest.TestCase):

    def test_store_params_schema(self):
        self.assertIsInstance(
            STORE_PARAMS_SCHEMA,
            JsonObjectSchema
        )
        self.assertIn(
            'key',
            STORE_PARAMS_SCHEMA.properties
        )
        self.assertIn(
            'secret',
            STORE_PARAMS_SCHEMA.properties
        )


    def test_open_params_schema(self):
        self.assertIsInstance(
            OPEN_PARAMS_SCHEMA,
            JsonObjectSchema
        )
        self.assertIn(
            'variable_names',
            OPEN_PARAMS_SCHEMA.properties
        )
        self.assertIn(
            'bbox',
            OPEN_PARAMS_SCHEMA.properties
        )
        self.assertIn(
            'spatial_res',
            OPEN_PARAMS_SCHEMA.properties
        )
        self.assertIn(
            'time_range',
            OPEN_PARAMS_SCHEMA.properties
        )
        self.assertIn(
            'time_tolerance',
            OPEN_PARAMS_SCHEMA.properties
        )
