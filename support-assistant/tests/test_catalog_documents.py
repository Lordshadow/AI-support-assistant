import unittest

from ingestion.catalog_documents import CatalogProduct, build_product_chunks


class TestCatalogDocuments(unittest.TestCase):
    def test_normalization_drops_live_fields_and_specs_from_vectors(self):
        product = CatalogProduct.model_validate_source({
            "id": 141,
            "title": "Pulse Buds 141",
            "description": "Pulse Buds 141 has an extended battery life. It supports fast pairing.",
            "price": 999,
            "stock": 4,
            "specifications": [{"label": "Weight", "value": "777 grams"}],
            "faqs": [{"question": "How long?", "answer": "Up to 40 hours of playback."}],
        })
        chunks = build_product_chunks(product, doc_version=product.content_hash())
        self.assertGreaterEqual(len(chunks), 5)
        self.assertLessEqual(len(chunks), 15)
        self.assertTrue(all(c["text"].startswith("Pulse Buds 141 - ") for c in chunks))
        self.assertTrue(all(c["metadata"]["product_id"] == "141" for c in chunks))
        self.assertTrue(all(c["metadata"]["name"] == "Pulse Buds 141" for c in chunks))
        self.assertTrue(all(c["metadata"]["brand"] == "Generic" for c in chunks))
        self.assertTrue(all(c["metadata"]["category"] == "General" for c in chunks))
        self.assertTrue(all(c["metadata"]["source_type"] == "catalog" for c in chunks))
        self.assertTrue(all(c["metadata"]["doc_version"] == product.content_hash() for c in chunks))
        combined = " ".join(c["text"] for c in chunks).lower()
        self.assertNotIn("999", combined)
        self.assertNotIn("777 grams", combined)

    def test_exact_model_numbers_preserved_and_lookalike_distinction(self):
        p141 = CatalogProduct.model_validate_source({
            "id": "P1041",
            "name": "Pulse Buds 141",
            "brand": "NovaAudio",
            "category": "electronics",
            "description": "The 141 model delivers 42 hours battery playback with 10mm dynamic bass drivers.",
            "faqs": [{"question": "Is this 141?", "answer": "Yes, this is model 141, not 131."}],
        })
        p131 = CatalogProduct.model_validate_source({
            "id": "P1031",
            "name": "Pulse Buds 131",
            "brand": "NovaAudio",
            "category": "electronics",
            "description": "The 131 model delivers 60 hours battery playback with 13mm dynamic sound drivers.",
            "faqs": [{"question": "Is this 131?", "answer": "Yes, this is model 131, not 141."}],
        })

        chunks141 = build_product_chunks(p141, doc_version="v1")
        chunks131 = build_product_chunks(p131, doc_version="v1")

        self.assertTrue(all("141" in c["text"] for c in chunks141))
        self.assertTrue(all(c["metadata"]["product_id"] == "P1041" for c in chunks141))

        self.assertTrue(all("131" in c["text"] for c in chunks131))
        self.assertTrue(all(c["metadata"]["product_id"] == "P1031" for c in chunks131))

        # Check content hashes are distinct
        self.assertNotEqual(p141.content_hash(), p131.content_hash())

    def test_strips_boilerplate_navigation_and_volatile_terms(self):
        product = CatalogProduct.model_validate_source({
            "id": "P-TEST",
            "name": "Smart Earbuds",
            "description": (
                "Home > Electronics > Audio\n"
                "Skip to content\n"
                "Add to cart\n"
                "Buy now\n"
                "Price: 1999 INR\n"
                "In stock: Available\n"
                "Order status: Shipped\n"
                "Smart Earbuds feature active noise cancellation and crystal clear microphones for phone calls."
            ),
            "faqs": [{"question": "Does it have ANC?", "answer": "Yes, active noise cancellation up to 32dB."}],
        })
        chunks = build_product_chunks(product, doc_version="v1")
        combined = " ".join(c["text"] for c in chunks).lower()

        self.assertNotIn("home > electronics", combined)
        self.assertNotIn("skip to content", combined)
        self.assertNotIn("add to cart", combined)
        self.assertNotIn("buy now", combined)
        self.assertNotIn("price: 1999", combined)
        self.assertNotIn("in stock", combined)
        self.assertNotIn("order status", combined)
        self.assertIn("active noise cancellation", combined)

    def test_specs_change_does_not_change_vector_content_fingerprint(self):
        source = {"id": "P1", "name": "Speaker 141", "description": "Speaker 141 produces clear audio."}
        first = CatalogProduct.model_validate_source({**source, "specifications": [{"label": "Weight", "value": "1 kg"}]})
        second = CatalogProduct.model_validate_source({**source, "specifications": [{"label": "Weight", "value": "2 kg"}]})
        self.assertEqual(first.content_hash(), second.content_hash())

    def test_live_price_and_stock_changes_do_not_change_knowledge_fingerprint(self):
        base = {"id": "P1", "name": "Speaker 141", "description": "Clear sound."}
        first = CatalogProduct.model_validate_source({**base, "price": 1999, "in_stock": True})
        second = CatalogProduct.model_validate_source({**base, "price": 2999, "in_stock": False})
        self.assertEqual(first.content_hash(), second.content_hash())

    def test_malformed_faq_is_rejected_for_item_level_failure(self):
        with self.assertRaises(Exception):
            CatalogProduct.model_validate_source({"id": "P1", "name": "Speaker", "faqs": ["not a Q&A"]})

    def test_common_store_product_fields_and_html_are_normalized(self):
        product = CatalogProduct.model_validate_source({
            "id": 314,
            "title": "Wireless Speaker",
            "vendor": "AudioCo",
            "product_type": "Speakers",
            "body_html": "<p>Portable sound &amp; clear vocals.</p><script>ignore this</script>",
            "categories": [{"name": "Audio"}],
            "attributes": [{"name": "Battery", "options": ["12 hours"]}],
            "price": "1299.00",
            "stock_status": "instock",
        })

        self.assertEqual(product.product_id, "314")
        self.assertEqual(product.brand, "AudioCo")
        self.assertEqual(product.category, "Speakers")
        self.assertIn("Portable sound & clear vocals.", product.description)
        self.assertNotIn("ignore this", product.description)
        self.assertEqual(product.normalized_specs()[0].label, "Battery")
        self.assertEqual(product.normalized_specs()[0].value, "12 hours")
        self.assertIsNone(product.price)  # Fractional vendor prices are not coerced into the legacy integer cache.
        self.assertTrue(product.in_stock)
        chunks = build_product_chunks(product, doc_version="v1")
        self.assertTrue(all("<p>" not in chunk["text"] for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
