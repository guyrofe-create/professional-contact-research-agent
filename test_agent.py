import unittest
import json
import pandas as pd
from unittest.mock import MagicMock, patch

import agent


class IdentityValidationTests(unittest.TestCase):
    def test_exact_hebrew_person_name_required(self):
        self.assertTrue(agent.name_match("שירלי לויט דרסן", "שירלי לויט דרסן יועצת הנקה מוסמכת"))
        self.assertFalse(agent.name_match("שירלי לויט דרסן", "רשות המסים של מחוז בואנוס איירס"))

    def test_wrong_foreign_email_is_rejected(self):
        score = agent.candidate_score(
            "cep.creditos@arba.gov.ar",
            "https://web.arba.gov.ar/catastro-y-geodesia",
            "שירלי לויט דרסן יועצת הנקה",
            "רשות המסים",
            "catastro y geodesia",
            "שירלי לויט דרסן",
            "lactation",
            True,
        )
        self.assertIsNone(score)

    def test_unrelated_generic_email_is_rejected(self):
        score = agent.candidate_score(
            "visitors@kan.org.il",
            "https://www.kan.org.il/contact-us/",
            "ג'ולי קרקו יועצת הנקה",
            "כאן תאגיד השידור",
            "פניות הציבור",
            "ג'ולי קרקו",
            "lactation",
            True,
        )
        self.assertIsNone(score)

    def test_personal_email_next_to_name_is_accepted(self):
        score = agent.candidate_score(
            "yael.doula@gmail.com",
            "https://yaeldoula.co.il/contact",
            "יעל כהן דולה ותומכת לידה צור קשר",
            "יעל כהן דולה",
            "יעל כהן yael.doula@gmail.com",
            "יעל כהן",
            "doula",
            True,
        )
        self.assertGreaterEqual(score, 75)

    def test_professional_site_generic_mail_is_accepted(self):
        score = agent.candidate_score(
            "info@drcohen.co.il",
            "https://drcohen.co.il/contact",
            "דוד כהן מומחה ביילוד וגינקולוגיה מרפאה פרטית",
            "דוד כהן רופא נשים",
            "צור קשר למרפאת דוד כהן",
            "דוד כהן",
            "gynecologist",
            True,
        )
        self.assertGreaterEqual(score, 75)

    def test_blocked_utility_domains(self):
        self.assertTrue(agent.blocked_url("https://stockanalysis.com/contact/"))
        self.assertTrue(agent.blocked_url("https://www.google.com/search?q=name"))
        self.assertFalse(agent.blocked_url("https://www.ima.org.il/doctorprofile"))

    def test_general_information_article_is_not_an_identity_source(self):
        self.assertFalse(agent.allowed_identity_page(
            "https://example.co.il/articles/dr-cohen-interview",
            "ראיון עם דוד כהן גינקולוג",
            "דוד כהן מומחה בגינקולוגיה",
            "דוד כהן",
            "gynecologist",
        ))

    def test_professional_directory_profile_is_allowed(self):
        self.assertTrue(agent.allowed_identity_page(
            "https://www.infomed.co.il/experts/12345/",
            "דוד כהן רופא נשים",
            "דוד כהן מומחה ביילוד וגינקולוגיה",
            "דוד כהן",
            "gynecologist",
        ))

    def test_directory_support_email_is_not_attributed_to_doctor(self):
        score = agent.candidate_score(
            "cs@infomed.co.il", "https://www.infomed.co.il/contact-us/", "שירות לקוחות", "צור קשר",
            "שירות לקוחות cs@infomed.co.il", "דוד כהן", "gynecologist", True,
            "דוד כהן מומחה ביילוד וגינקולוגיה", "https://www.infomed.co.il/experts/12345/",
        )
        self.assertIsNone(score)

    def test_moh_dataset_is_provenance_not_identity_page(self):
        self.assertFalse(agent.usable_identity_seed(
            "https://data.gov.il/he/datasets/ministry-health/database-of-doctors-licenses-moh/123"
        ))

    def test_search_snippet_does_not_need_to_repeat_specialty(self):
        hit = {"href": "https://hospital.example/dr-cohen", "title": "דוד כהן", "body": "פרופיל רופא"}
        state = {}
        fake_engine = MagicMock()
        fake_engine.text.return_value = [hit]
        with patch.object(agent, "DDGS", return_value=fake_engine):
            results = list(agent.search_web("דוד כהן", "gynecologist", state=state))
        self.assertTrue(results)
        self.assertGreater(state["results"], 0)

    def test_placeholder_and_non_outreach_emails_are_rejected(self):
        for email in ("dr@example.com", "john.doe@company.com", "mymail@mailservice.com", "rfu-refunds@tlvmc.gov.il", "zimun@tlvmc.gov.il"):
            with self.subTest(email=email):
                self.assertFalse(agent.valid_email(email))

    def test_obfuscated_and_cloudflare_emails_are_extracted(self):
        html = '''<html><head><title>יעל כהן דולה</title></head><body>
        <p>יעל כהן, דולה. yael [at] birth [dot] co.il</p>
        <span data-email="clinic@birth.co.il"></span></body></html>'''
        found, _, _, _, _ = agent.extract("https://birth.co.il/about", html)
        emails = {item[0] for item in found}
        self.assertIn("yael@birth.co.il", emails)
        self.assertIn("clinic@birth.co.il", emails)

    def test_same_official_site_contact_page_inherits_identity(self):
        score = agent.candidate_score(
            "office@drcohen.co.il", "https://drcohen.co.il/contact", "צרו קשר", "צור קשר",
            "office@drcohen.co.il", "דוד כהן", "gynecologist", True,
            "דוד כהן מומחה בגינקולוגיה", "https://drcohen.co.il/about",
        )
        self.assertGreaterEqual(score, 75)

    def test_unrelated_large_hospital_department_is_rejected(self):
        score = agent.candidate_score(
            "finance@tlvmc.gov.il", "https://www.tasmc.org.il/contact", "צור קשר בית חולים", "צור קשר",
            "מחלקת כספים", "דוד כהן", "gynecologist", True,
            "דוד כהן מומחה בגינקולוגיה", "https://www.tasmc.org.il/doctors/dr-cohen",
        )
        self.assertIsNone(score)

    def test_relevant_hospital_department_email_is_accepted(self):
        score = agent.candidate_score(
            "ivf-unit@tlvmc.gov.il", "https://www.tasmc.org.il/doctors/dr-cohen",
            "דוד כהן מומחה פוריות IVF", "דוד כהן רופא פוריות",
            "יחידת IVF יצירת קשר ivf-unit@tlvmc.gov.il", "דוד כהן", "fertility_doctor", True,
            "דוד כהן מומחה פוריות", "https://www.tasmc.org.il/doctors/dr-cohen",
        )
        self.assertGreaterEqual(score, 75)

    def test_all_verified_alternate_emails_are_exported(self):
        row = {
            "algo_version": 5, "name": "מרכז בריאות האישה", "category": "womens_health_center",
            "priority": "A", "target_kind": "org", "seed_source": "", "email": "clinic@health.co.il",
            "email_type": "CLINIC_OR_ORGANIZATION", "confidence": 95, "source_url": "https://health.co.il/contact",
            "status": "VERIFIED", "evidence": "מרכז בריאות האישה", "matched_query": "seed", "extraction_method": "mailto",
            "alternate_emails": json.dumps([{"email": "manager@health.co.il", "confidence": 90, "source_url": "https://health.co.il/team", "evidence": "מנהלת המרכז", "matched_query": "seed", "extraction_method": "text"}]),
        }
        expanded = agent.expand_verified_contacts(pd.DataFrame([row]))
        self.assertEqual({"clinic@health.co.il", "manager@health.co.il"}, set(expanded.email))

    def test_research_crawls_official_contact_pages_and_keeps_multiple_emails(self):
        pages = {
            "https://clinic.co.il/about": '''<html><head><title>מרכז בריאות האישה אור</title></head><body>
                מרכז בריאות האישה <a href="/contact">צור קשר</a><a href="/team">צוות</a></body></html>''',
            "https://clinic.co.il/contact": '''<html><head><title>צור קשר</title></head><body>
                מרכז בריאות האישה <a href="mailto:clinic@clinic.co.il">מייל המרפאה</a>
                <span>john.doe@company.com</span></body></html>''',
            "https://clinic.co.il/team": '''<html><head><title>צוות</title></head><body>
                מרכז בריאות האישה מנהלת המרפאה manager@clinic.co.il</body></html>''',
        }

        def fake_fetch(url):
            return url, pages.get(url, "")

        hit = {"url": "https://clinic.co.il/about", "title": "מרכז בריאות האישה אור", "snippet": "", "query": "seed", "seed": True}
        with patch.object(agent, "search_web", return_value=iter([hit])), patch.object(agent, "fetch", side_effect=fake_fetch):
            result = agent.research({"name": "מרכז בריאות האישה אור", "category": "womens_health_center", "seed_source": "https://clinic.co.il/about"})
        emails = {item["email"] for item in agent.row_candidates(result)}
        self.assertEqual("VERIFIED", result["status"])
        self.assertEqual({"clinic@clinic.co.il", "manager@clinic.co.il"}, emails)

    def test_excel_sanitization_applies_to_string_dtype_and_control_chars(self):
        frame = pd.DataFrame({"evidence": pd.Series(["טקסט\x00פגום"], dtype="str")})
        safe = agent.excel_safe_frame(frame)
        self.assertEqual("טקסטפגום", safe.loc[0, "evidence"])

    def test_family_doctor_and_womens_health_categories_exist(self):
        self.assertIn("family_doctor", agent.CATEGORY_CONFIG)
        self.assertIn("clinic_manager", agent.CATEGORY_CONFIG)
        self.assertIn("womens_health_center", agent.CATEGORY_CONFIG)
        self.assertIn("community_clinic", agent.CATEGORY_CONFIG)


if __name__ == "__main__":
    unittest.main()
