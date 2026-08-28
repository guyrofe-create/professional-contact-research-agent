import unittest

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


if __name__ == "__main__":
    unittest.main()
