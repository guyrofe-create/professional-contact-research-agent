import unittest
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from unittest.mock import MagicMock, patch

import agent
import seed_targets


class IdentityValidationTests(unittest.TestCase):
    def test_search_circuit_opens_when_provider_silently_returns_only_empty_results(self):
        original=(agent.SEARCH_CALLS,agent.SEARCH_CIRCUIT_OPEN,agent.SEARCH_EMPTY_RESULTS_STREAK,agent.SEARCH_EMPTY_CIRCUIT_THRESHOLD)
        try:
            agent.SEARCH_CALLS=0; agent.SEARCH_CIRCUIT_OPEN=False; agent.SEARCH_EMPTY_RESULTS_STREAK=0; agent.SEARCH_EMPTY_CIRCUIT_THRESHOLD=5
            empty=MagicMock(); empty.text.return_value=[]
            with patch.object(agent,"DDGS",return_value=empty):
                for _ in range(5):agent._search_once('"דנה לוי" רופאת נשים',10)
            self.assertTrue(agent.SEARCH_CIRCUIT_OPEN)
        finally:
            agent.SEARCH_CALLS,agent.SEARCH_CIRCUIT_OPEN,agent.SEARCH_EMPTY_RESULTS_STREAK,agent.SEARCH_EMPTY_CIRCUIT_THRESHOLD=original

    def test_recovery_restores_only_safe_verified_rows(self):
        verified={"algo_version":agent.ALGO_VERSION,"physician_search_version":agent.PHYSICIAN_SEARCH_VERSION,"status":"VERIFIED","name":"דנה לוי","category":"gynecologist","email":"dana.levy@gmail.com","source_url":"https://dr-dana.example.co.il/","identity_url":"https://dr-dana.example.co.il/","evidence":"דנה לוי גינקולוגית"}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"recovered.jsonl"; path.write_text(json.dumps(verified,ensure_ascii=False)+"\n",encoding="utf-8")
            stored={("דנה לוי","gynecologist"):{"status":"PENDING_ALGO_UPGRADE","name":"דנה לוי","category":"gynecologist"}}
            restored=agent.restore_verified_recovery(stored,path)
        self.assertEqual(restored[("דנה לוי","gynecologist")]["status"],"VERIFIED")

    def test_safe_verified_physician_survives_search_version_upgrade(self):
        record={
            "algo_version":agent.ALGO_VERSION,
            "physician_search_version":agent.PHYSICIAN_SEARCH_VERSION-1,
            "status":"VERIFIED","name":"דנה לוי","category":"gynecologist",
            "email":"dana.levy@gmail.com","source_url":"https://dr-dana.example.co.il/",
            "identity_url":"https://dr-dana.example.co.il/","evidence":"דנה לוי גינקולוגית",
        }
        migrated=agent.migrate_checkpoint_row(record)
        self.assertEqual(migrated["status"],"VERIFIED")
        self.assertEqual(migrated["physician_search_version"],agent.PHYSICIAN_SEARCH_VERSION)

    def test_version_twelve_verified_contact_survives_search_upgrade(self):
        record={
            "algo_version":12,"physician_search_version":3,"status":"VERIFIED",
            "name":"דנה לוי","category":"gynecologist","email":"dana.levy@gmail.com",
            "source_url":"https://dr-dana.example.co.il/","identity_url":"https://dr-dana.example.co.il/",
            "evidence":"דנה לוי גינקולוגית",
        }
        migrated=agent.migrate_checkpoint_row(record)
        self.assertEqual("VERIFIED", migrated["status"])
        self.assertEqual(agent.ALGO_VERSION, migrated["algo_version"])

    def test_clinic_manager_is_researched_after_search_upgrade(self):
        record={
            "algo_version":agent.ALGO_VERSION,"physician_search_version":agent.PHYSICIAN_SEARCH_VERSION-1,
            "status":"NO_VERIFIED_PUBLIC_EMAIL","name":"דנה לוי מנהלת מרפאה","category":"clinic_manager",
        }
        migrated=agent.migrate_checkpoint_row(record)
        self.assertEqual("PENDING_ALGO_UPGRADE", migrated["status"])

    def test_cross_person_link_on_clinic_team_is_rejected(self):
        score=agent.candidate_score(
            "gilgold@gmail.com","https://clinic.example.co.il/team/gil-goldman",
            "גיל גולדמן רופא משפחה gilgold@gmail.com","ד״ר גיל גולדמן",
            "gilgold@gmail.com","נחום סגול","family_doctor",True,
            "נחום סגול מומחה רפואת משפחה","https://clinic.example.co.il/memb/nahum-segol",
        )
        self.assertIsNone(score)

    def test_clinic_location_is_not_a_clinic_manager_person(self):
        self.assertFalse(agent.valid_person_target_name("פתח תקווה","clinic_manager"))
        self.assertFalse(agent.valid_person_target_name("רמת אביב ב","clinic_manager"))
        self.assertTrue(agent.valid_person_target_name("נועה רז מנהלת מרפאה","clinic_manager"))

    def test_stored_cross_person_clinic_mail_is_not_send_eligible(self):
        record={
            "status":"VERIFIED","name":"נטלי זיגל","category":"family_doctor",
            "email":"manor@teamclinic360.co.il","source_url":"https://www.teamclinic360.co.il/",
            "identity_url":"https://www.teamclinic360.co.il/doctor/dr-natalie/",
            "evidence":"דוא״ל manor@teamclinic360.co.il","extraction_method":"linked_mailto",
        }
        self.assertFalse(agent.stored_candidate_still_safe(record))

    def test_physician_without_candidate_remains_retryable_before_limit(self):
        row={"name":"דנה לוי","category":"gynecologist","seed_source":""}
        def empty_search(*args, **kwargs):
            kwargs["state"].update({"queries": 4, "errors": 0, "results": 0, "provider": "fake", "circuit_open": False, "result_urls": []})
            return iter([])
        with patch.object(agent,"search_web",side_effect=empty_search):
            result=agent.research(row)
        self.assertEqual(result["status"],"PENDING_RESEARCH")
        self.assertEqual(result["resolution_reason"],"retry_scheduled")

    def test_all_doctor_searches_split_hmos_and_target_contact_pages(self):
        for category in ("family_doctor", "gynecologist", "fertility_doctor"):
            with self.subTest(category=category):
                queries=agent.search_queries("ד״ר דוד כהן", category, "12345")
                self.assertIn(agent.CATEGORY_CONFIG[category]["terms"][0], queries[0])
                for domain in agent.HMO_SEARCH_DOMAINS:
                    self.assertTrue(any(f"site:{domain}" in query for query in queries))
                self.assertTrue(any("צור קשר" in query for query in queries))
                self.assertTrue(any("12345" in query for query in queries))

    def test_clinic_manager_search_targets_role_hmo_and_contact_pages(self):
        queries=agent.search_queries("דנה לוי", "clinic_manager")
        self.assertTrue(any("מנהל מרפאה" in query for query in queries))
        self.assertTrue(any("site:meuhedet.co.il" in query for query in queries))
        self.assertTrue(any("דואר אלקטרוני" in query for query in queries))

    def test_family_doctor_does_not_inherit_generic_hmo_contact_page(self):
        score = agent.candidate_score(
            "clinic@clalit.org.il", "https://www.clalit.co.il/clinic/contact",
            "מרפאת הדרים צור קשר clinic@clalit.org.il", "מרפאת הדרים",
            "דואר אלקטרוני clinic@clalit.org.il", "דוד כהן", "family_doctor", True,
            "דוד כהן מומחה ברפואת משפחה מרפאת הדרים", "https://www.clalit.co.il/doctor/dr-cohen",
            verified_clinic_route=True,
        )
        self.assertIsNone(score)

    def test_exact_doctor_profile_can_publish_its_clinic_mailbox(self):
        score = agent.candidate_score(
            "clinic@clalit.org.il", "https://www.clalit.co.il/doctor/dr-cohen",
            "דוד כהן מומחה ברפואת משפחה clinic@clalit.org.il", "דוד כהן רפואת משפחה",
            "דוד כהן מומחה ברפואת משפחה clinic@clalit.org.il", "דוד כהן", "family_doctor", True,
            "דוד כהן מומחה ברפואת משפחה", "https://www.clalit.co.il/doctor/dr-cohen",
        )
        self.assertGreaterEqual(score, 75)

    def test_new_verified_record_requires_name_and_specialty_proof(self):
        record={
            "algo_version":agent.ALGO_VERSION,"verification_schema_version":agent.VERIFICATION_SCHEMA_VERSION,
            "identity_name_verified":True,"identity_specialty_verified":True,
            "status":"VERIFIED","name":"דוד כהן","category":"gynecologist",
            "email":"david.cohen@gmail.com","source_url":"https://dr-cohen.example.co.il/",
            "identity_url":"https://dr-cohen.example.co.il/","evidence":"דוד כהן רופא נשים",
        }
        self.assertTrue(agent.stored_candidate_still_safe(record))
        record["identity_specialty_verified"]=False
        self.assertFalse(agent.stored_candidate_still_safe(record))

    def test_legacy_wrong_specialty_and_publisher_contacts_are_demoted(self):
        rows=[
            {"name":"דוד מיכאל","category":"gynecologist","email":"mdavid652@gmail.com","source_url":"https://doctors.example.co.il/dermatology/michael-david","identity_url":"https://doctors.example.co.il/dermatology/michael-david","evidence":"פרופ מיכאל דוד מומחה לרפואת עור"},
            {"name":"דורון אביטל","category":"gynecologist","email":"afulanet@gmail.com","source_url":"https://afulanet.co.il/contact","identity_url":"https://afulanet.co.il/story/doron-avital","evidence":"צור קשר עם מערכת החדשות"},
            {"name":"דן זאבי","category":"gynecologist","email":"edt.eilat@gmail.com","source_url":"https://eilat-guide.co.il/contact","identity_url":"https://eilat-guide.co.il/doctor/dan","evidence":"צור קשר מדריך העסקים"},
            {"name":"אורנה שטטר","category":"family_doctor","email":"fps.israel@gmail.com","source_url":"https://fps.org.il/contact","identity_url":"https://fps.org.il/therapists/orna","evidence":"האגודה לפסיכותרפיה ממוקדת"},
        ]
        for row in rows:
            with self.subTest(email=row["email"]):
                migrated=agent.migrate_checkpoint_row({"algo_version":12,"status":"VERIFIED"}|row)
                self.assertEqual("PENDING_ALGO_UPGRADE",migrated["status"])

    def test_email_in_exact_identity_search_snippet_is_accepted_when_page_is_dynamic(self):
        row={"name":"דוד כהן","category":"family_doctor","seed_source":""}
        hit={
            "url":"https://www.clalit.co.il/he/sefersherut/pages/doctor.aspx?id=1",
            "title":"דוד כהן - מומחה ברפואת משפחה",
            "snippet":"דוד כהן מומחה ברפואת משפחה, מרפאת הדרים, clinic@clalit.org.il",
            "query":"דוד כהן רפואת משפחה","seed":False,
        }
        def fake_search(*args, **kwargs):
            kwargs["state"].update({"queries":1,"errors":0,"results":1,"provider":"fake","circuit_open":False,"result_urls":[hit["url"]]})
            return iter([hit])
        with patch.object(agent,"search_web",side_effect=fake_search), patch.object(agent,"fetch",return_value=(hit["url"],"")):
            result=agent.research(row)
        self.assertEqual("VERIFIED", result["status"])
        self.assertEqual("clinic@clalit.org.il", result["email"])
        self.assertEqual("search_snippet", result["extraction_method"])

    def test_family_doctor_terminal_v11_result_is_researched_again(self):
        old = {"algo_version": 11, "name": "דוד כהן", "category": "family_doctor", "status": "NO_VERIFIED_PUBLIC_EMAIL"}
        self.assertEqual("PENDING_ALGO_UPGRADE", agent.migrate_checkpoint_row(old)["status"])

    def test_every_physician_terminal_v11_result_is_researched_again(self):
        for category in ("family_doctor", "gynecologist", "fertility_doctor"):
            old = {"algo_version": 11, "name": "דוד כהן", "category": category, "status": "NO_VERIFIED_PUBLIC_EMAIL"}
            with self.subTest(category=category):
                self.assertEqual("PENDING_ALGO_UPGRADE", agent.migrate_checkpoint_row(old)["status"])

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

    def test_business_directory_email_is_never_attributed_to_doctor(self):
        score = agent.candidate_score(
            "1800@d.co.il", "https://www.d.co.il/80213191/46500/",
            "ד״ר אביגיל מעיני גינקולוגית", "ד״ר אביגיל מעיני",
            "שירות לקוחות 1800@d.co.il", "אביגיל מעיני", "gynecologist", True,
        )
        self.assertIsNone(score)

    def test_generic_hospital_directory_is_not_identity_page(self):
        self.assertFalse(agent.allowed_identity_page(
            "https://www.szmc.org.il/doctors/", "רופאים בשערי צדק",
            "ד״ר אבי צפריר רופא נשים ד״ר אדם פרקש קרדיולוג",
            "אבי צפריר", "gynecologist",
        ))

    def test_generic_hospital_department_is_not_person_identity_page(self):
        self.assertFalse(agent.allowed_identity_page(
            "https://www.laniado.org.il/mahlakot/ivf/", "יחידת IVF",
            "אביטל גלאובך צוות רפואי יחידת פוריות",
            "אביטל גלאובך", "gynecologist",
        ))

    def test_exact_profile_link_is_resolved_from_directory(self):
        html = '''<html><body><ul>
        <li>ד״ר אבי צפריר <a href="/doctors/tsafrir-avi/">לפרופיל</a></li>
        <li>ד״ר אדם פרקש <a href="/doctors/farkash-adam/">לפרופיל</a></li>
        </ul></body></html>'''
        self.assertEqual(
            ["https://hospital.org.il/doctors/tsafrir-avi/"],
            agent.identity_profile_links("https://hospital.org.il/doctors/", html, "אבי צפריר"),
        )

    def test_unrelated_email_on_hospital_list_is_rejected(self):
        score = agent.candidate_score(
            "aflek1@yahoo.com", "https://www.szmc.org.il/doctors/",
            "אבי צפריר רופא נשים אברהם פלד aflek1@yahoo.com", "רופאים בשערי צדק",
            "אברהם פלד aflek1@yahoo.com", "אבי צפריר", "gynecologist", False,
        )
        self.assertIsNone(score)

    def test_structural_context_does_not_cross_people(self):
        html = '''<html><head><title>רופאים</title></head><body><ul>
        <li>ד״ר אבי צפריר, רופא נשים</li>
        <li>ד״ר אדם פרקש <a href="mailto:adam@examplehospital.org.il">adam@examplehospital.org.il</a></li>
        </ul></body></html>'''
        found, _, text, title, _ = agent.extract("https://hospital.org.il/doctors", html)
        email, context, _ = next(x for x in found if x[0] == "adam@examplehospital.org.il")
        self.assertNotIn("אבי צפריר", context)
        self.assertIsNone(agent.candidate_score(email, "https://hospital.org.il/doctors", text, title, context, "אבי צפריר", "gynecologist", False))

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

    def test_search_circuit_stops_repeated_provider_failures(self):
        old = (agent.SEARCH_CALLS, agent.SEARCH_CONSECUTIVE_FAILURES, agent.SEARCH_CIRCUIT_OPEN, agent.SEARCH_CIRCUIT_FAILURES)
        try:
            agent.SEARCH_CALLS = 0
            agent.SEARCH_CONSECUTIVE_FAILURES = 0
            agent.SEARCH_CIRCUIT_OPEN = False
            agent.SEARCH_CIRCUIT_FAILURES = 2
            with patch.object(agent, "_search_once", side_effect=RuntimeError("provider unavailable")) as search:
                list(agent.search_web("דוד כהן", "gynecologist", state={}))
                state = {}
                list(agent.search_web("שרה לוי", "gynecologist", state=state))
                list(agent.search_web("רחל ישראלי", "gynecologist", state={}))
            self.assertEqual(2, search.call_count)
            self.assertTrue(state["circuit_open"])
        finally:
            agent.SEARCH_CALLS, agent.SEARCH_CONSECUTIVE_FAILURES, agent.SEARCH_CIRCUIT_OPEN, agent.SEARCH_CIRCUIT_FAILURES = old

    def test_no_results_is_not_a_provider_outage(self):
        old = (agent.SEARCH_CALLS, agent.SEARCH_CONSECUTIVE_FAILURES, agent.SEARCH_CIRCUIT_OPEN)
        try:
            agent.SEARCH_CALLS = 0
            agent.SEARCH_CONSECUTIVE_FAILURES = 0
            agent.SEARCH_CIRCUIT_OPEN = False
            with patch.object(agent, "_search_once", side_effect=RuntimeError("No results found.")) as search:
                state = {}
                self.assertEqual([], list(agent.search_web("דוד כהן", "gynecologist", state=state)))
            self.assertEqual(len(agent.search_queries("דוד כהן", "gynecologist")), search.call_count)
            self.assertEqual(0, state["errors"])
            self.assertFalse(agent.SEARCH_CIRCUIT_OPEN)
        finally:
            agent.SEARCH_CALLS, agent.SEARCH_CONSECUTIVE_FAILURES, agent.SEARCH_CIRCUIT_OPEN = old

    def test_person_is_not_assigned_sales_or_international_route(self):
        for email in ("sales@miok.co.il", "international@raphaelhospitals.co.il", "logistics@hospital.org.il"):
            with self.subTest(email=email):
                score = agent.candidate_score(
                    email, "https://hospital.org.il/doctors/dr-cohen", "דוד כהן רופא נשים",
                    "דוד כהן רופא נשים", f"דוד כהן רופא נשים {email}", "דוד כהן",
                    "gynecologist", True, "דוד כהן רופא נשים", "https://hospital.org.il/doctors/dr-cohen",
                )
                self.assertIsNone(score)

    def test_cross_company_footer_email_is_rejected(self):
        score = agent.candidate_score(
            "info2@medica.co.il", "https://raphaelhospitals.co.il/doctors/dr-cohen",
            "דוד כהן רופא נשים info2@medica.co.il", "דוד כהן רופא נשים",
            "דוד כהן info2@medica.co.il", "דוד כהן", "gynecologist", True,
            "דוד כהן רופא נשים", "https://raphaelhospitals.co.il/doctors/dr-cohen",
        )
        self.assertIsNone(score)

    def test_version_seven_checkpoint_is_migrated_without_losing_candidate(self):
        old = {
            "algo_version": 7, "name": "דוד כהן", "category": "gynecologist",
            "status": "VERIFIED", "email": "sales@miok.co.il", "confidence": 90,
            "source_url": "https://miok.co.il/doctors/123", "identity_url": "https://miok.co.il/doctors/123",
            "evidence": "דוד כהן רופא נשים sales@miok.co.il",
        }
        migrated = agent.migrate_checkpoint_row(old)
        self.assertEqual(agent.ALGO_VERSION, migrated["algo_version"])
        self.assertEqual("PENDING_ALGO_UPGRADE", migrated["status"])
        self.assertIn("sales@miok.co.il", migrated["previous_candidate"])

    def test_version_eight_terminal_result_is_preserved(self):
        old = {"algo_version": 8, "name": "דוד כהן", "category": "gynecologist", "status": "NO_VERIFIED_PUBLIC_EMAIL"}
        migrated = agent.migrate_checkpoint_row(old)
        self.assertEqual(agent.ALGO_VERSION, migrated["algo_version"])
        self.assertEqual("PENDING_ALGO_UPGRADE", migrated["status"])

    def test_marketing_agency_contact_is_not_attributed_to_a_person(self):
        old = {"algo_version": 9, "name": "אורנית טפירו ישראל", "category": "doula", "status": "VERIFIED", "email": "office@get-marketing.co.il", "source_url": "https://get-marketing.co.il/#contact", "identity_url": "https://get-marketing.co.il/oranit-dula/"}
        migrated = agent.migrate_checkpoint_row(old)
        self.assertEqual("PENDING_ALGO_UPGRADE", migrated["status"])

    def test_generic_medical_page_is_not_a_person(self):
        self.assertFalse(agent.valid_person_target_name("IVF הפריה חוץ גופית", "embryologist"))
        self.assertFalse(agent.valid_person_target_name("לידה כמסע", "childbirth_educator"))

    def test_queue_immediately_processes_never_searched_rows_and_round_robins_categories(self):
        rows = [
            {"name": "אחד כהן", "category": "gynecologist"},
            {"name": "שניים כהן", "category": "gynecologist"},
            {"name": "שלוש לוי", "category": "family_doctor"},
        ]
        future = "2099-01-01T00:00:00+00:00"
        stored = {(row["name"], row["category"]): {"status": "PENDING_SEARCH_PROVIDER", "search_queries": 0, "next_retry_at": future} for row in rows}
        queue = agent.build_research_queue(rows, stored, datetime.now(timezone.utc), 10)
        self.assertEqual(3, len(queue))
        self.assertEqual({"gynecologist", "family_doctor"}, {queue[0]["category"], queue[1]["category"]})

    def test_queue_prioritizes_requested_contact_categories(self):
        rows = [
            {"name": "יעל ישראלי", "category": "doula", "seed_source": "https://yael.example.co.il"},
            {"name": "דוד כהן", "category": "family_doctor"},
            {"name": "שרה לוי", "category": "gynecologist"},
            {"name": "נועה רז מנהלת מרפאה", "category": "clinic_manager"},
        ]
        queue = agent.build_research_queue(rows, {}, datetime.now(timezone.utc), 3)
        self.assertEqual(set(agent.PRIMARY_CONTACT_CATEGORIES), {row["category"] for row in queue})

    def test_queue_respects_retry_time_instead_of_forcing_deferred_work(self):
        row = {"name": "דוד כהן", "category": "family_doctor"}
        stored = {("דוד כהן", "family_doctor"): {
            "status": "PENDING_SEARCH_PROVIDER", "search_queries": 4,
            "next_retry_at": "2099-01-01T00:00:00+00:00",
        }}
        self.assertEqual([], agent.build_research_queue([row], stored, datetime.now(timezone.utc), 10))

    def test_physician_search_becomes_terminal_after_bounded_attempts(self):
        row = {
            "name": "דנה לוי", "category": "gynecologist", "seed_source": "",
            "retry_count": agent.MAX_RESEARCH_ATTEMPTS - 1,
        }
        def empty_search(*args, **kwargs):
            kwargs["state"].update({"queries": 4, "errors": 0, "results": 0, "provider": "fake", "circuit_open": False, "result_urls": []})
            return iter([])
        with patch.object(agent, "search_web", side_effect=empty_search):
            result = agent.research(row)
        self.assertEqual("NO_VERIFIED_PUBLIC_EMAIL", result["status"])
        self.assertEqual("exhausted_search_attempts", result["resolution_reason"])

    def test_repeated_identical_search_results_finish_early(self):
        hit = {"url": "https://clinic.example.co.il/dr-levy", "title": "דנה לוי רופאת נשים", "snippet": "", "query": '"דנה לוי"', "seed": False}
        row = {
            "name": "דנה לוי", "category": "gynecologist", "seed_source": "",
            "retry_count": 1, "unchanged_search_count": agent.MAX_UNCHANGED_SEARCHES - 1,
            "previous_search_fingerprint": f'{agent.zlib.crc32(hit["url"].encode("utf-8")) & 0xffffffff:08x}',
        }
        def fake_search(*args, **kwargs):
            kwargs["state"].update({"queries": 1, "errors": 0, "results": 1, "provider": "fake", "circuit_open": False, "result_urls": [hit["url"]]})
            return iter([hit])
        html = "<html><head><title>דנה לוי רופאת נשים</title></head><body>דנה לוי מומחית בגינקולוגיה</body></html>"
        with patch.object(agent, "search_web", side_effect=fake_search), patch.object(agent, "fetch", return_value=(hit["url"], html)):
            result = agent.research(row)
        self.assertEqual("NO_VERIFIED_PUBLIC_EMAIL", result["status"])
        self.assertEqual("exhausted_search_attempts", result["resolution_reason"])

    def test_removed_targets_are_archived_not_counted_as_active(self):
        stored = {
            ("דוד כהן", "gynecologist"): {"name": "דוד כהן", "category": "gynecologist", "status": "VERIFIED"},
            ("ועידת רפואה", "family_doctor"): {"name": "ועידת רפואה", "category": "family_doctor", "status": "VERIFIED"},
        }
        with tempfile.TemporaryDirectory() as directory:
            active = agent.retain_active_checkpoint(stored, [{"name": "דוד כהן", "category": "gynecologist"}], Path(directory))
            self.assertEqual([("דוד כהן", "gynecologist")], list(active))
            self.assertIn("ועידת רפואה", (Path(directory) / "retired_targets.jsonl").read_text(encoding="utf-8"))

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
            "דוד כהן מומחה פוריות יחידת IVF יצירת קשר ivf-unit@tlvmc.gov.il", "דוד כהן", "fertility_doctor", True,
            "דוד כהן מומחה פוריות", "https://www.tasmc.org.il/doctors/dr-cohen",
        )
        self.assertGreaterEqual(score, 75)

    def test_hospital_route_without_person_in_email_context_is_rejected(self):
        score = agent.candidate_score(
            "amnioticfluid@hmc.co.il", "https://hmc.co.il/unit/amniotic-fluid",
            "דוד כהן רופא נשים יחידת מי שפיר", "יחידת מי שפיר",
            "יחידת מי שפיר amnioticfluid@hmc.co.il", "דוד כהן", "gynecologist", True,
            "דוד כהן רופא נשים", "https://hmc.co.il/doctors/dr-cohen", True,
        )
        self.assertIsNone(score)

    def test_url_encoded_email_is_normalized(self):
        self.assertEqual("info@harechem.com", agent.norm_email("%20info@harechem.com"))
        self.assertTrue(agent.valid_email(agent.norm_email("%20info@harechem.com")))

    def test_shared_role_address_is_retained_as_non_personalized_route(self):
        old = {
            "algo_version": agent.ALGO_VERSION, "physician_search_version": agent.PHYSICIAN_SEARCH_VERSION - 1,
            "name": "דוד כהן", "category": "gynecologist",
            "status": "VERIFIED", "email": "clinic@hospital.org.il",
            "source_url": "https://hospital.org.il/doctors/dr-cohen",
            "identity_url": "https://hospital.org.il/doctors/dr-cohen",
            "evidence": "דוד כהן רופא נשים clinic@hospital.org.il",
            "verification_schema_version": agent.VERIFICATION_SCHEMA_VERSION,
            "identity_name_verified": True, "identity_specialty_verified": True,
            "shared_target_count": 12,
        }
        migrated = agent.migrate_checkpoint_row(old)
        self.assertEqual(agent.ALGO_VERSION, migrated["algo_version"])
        self.assertEqual("VERIFIED", migrated["status"])
        self.assertFalse(migrated["verification_review_required"])
        self.assertEqual("clinic@hospital.org.il", migrated["email"])

    def test_non_physician_search_keeps_trying_after_unusable_hits(self):
        calls = []
        def fake_search(query, max_results):
            calls.append(query)
            return ([{"href": f"https://example.org/{len(calls)}", "title": "שרה כהן דולה", "body": ""}], "fake")
        with patch.object(agent, "_search_once", side_effect=fake_search):
            list(agent.search_web("שרה כהן", "doula", state={}))
        self.assertEqual(len(agent.search_queries("שרה כהן", "doula")), len(calls))

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

    def test_shared_clinic_email_is_retained_and_marked(self):
        rows = pd.DataFrame([
            {"name": "דוד כהן", "category": "gynecologist", "status": "VERIFIED", "email": "clinic@health.co.il", "confidence": 90, "alternate_emails": "[]"},
            {"name": "שרה לוי", "category": "gynecologist", "status": "VERIFIED", "email": "clinic@health.co.il", "confidence": 88, "alternate_emails": "[]"},
        ])
        expanded = agent.annotate_shared_contacts(agent.expand_verified_contacts(rows))
        self.assertEqual(2, len(expanded))
        self.assertTrue(expanded.shared_contact.all())
        self.assertEqual({2}, set(expanded.shared_target_count))
        self.assertEqual(1, len(expanded.drop_duplicates(subset=["email"])))

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
        self.assertEqual("https://clinic.co.il/about", result["identity_url"])

    def test_excel_sanitization_applies_to_string_dtype_and_control_chars(self):
        frame = pd.DataFrame({"evidence": pd.Series(["טקסט\x00פגום"], dtype="str")})
        safe = agent.excel_safe_frame(frame)
        self.assertEqual("טקסטפגום", safe.loc[0, "evidence"])

    def test_family_doctor_and_womens_health_categories_exist(self):
        self.assertIn("family_doctor", agent.CATEGORY_CONFIG)
        self.assertIn("clinic_manager", agent.CATEGORY_CONFIG)
        self.assertIn("womens_health_center", agent.CATEGORY_CONFIG)
        self.assertIn("community_clinic", agent.CATEGORY_CONFIG)

    def test_department_role_addresses_are_classified_as_institutional(self):
        for email in ("ivfrec@hospital.org.il", "og-clinic@hospital.org.il", "nashim@hospital.org.il"):
            with self.subTest(email=email):
                self.assertEqual("CLINIC_OR_ORGANIZATION", agent.classify(email, "gynecologist"))

    def test_person_deduplication_ignores_name_order_and_titles(self):
        first = seed_targets.person_identity_key("ד״ר עדי פוקס", "family_doctor")
        second = seed_targets.person_identity_key("פוקס עדי", "family_doctor")
        self.assertEqual(first, second)

    def test_navigation_titles_are_not_added_as_targets(self):
        rows = []
        seed_targets.add(rows, "אודות", "lactation", "https://example.org/about")
        seed_targets.add(rows, "דף הבית", "parenting_center", "https://example.org/")
        self.assertEqual([], rows)

    def test_generic_web_pages_are_not_person_targets(self):
        rows = []
        seed_targets.add(rows, "ועידת ישראל לרפואת משפחה 2024", "family_doctor", "https://example.org/conf", "web")
        seed_targets.add(rows, "רופא משפחה. יומן", "family_doctor", "https://example.org/book", "web")
        seed_targets.add(rows, "IVF הפריה חוץ גופית", "embryologist", "https://example.org/ivf", "web")
        seed_targets.add(rows, "התמחות ברפואת משפחה", "family_doctor", "https://example.org/residency", "web")
        seed_targets.add(rows, "ייעוץ רפואת ילדים", "family_doctor", "https://example.org/pediatrics", "web")
        self.assertEqual([], rows)

    def test_named_clinic_manager_is_retained_but_generic_role_is_rejected(self):
        rows = []
        seed_targets.add(rows, "נועה רז מנהלת מרפאה", "clinic_manager", "https://clinic.example.co.il/team", "web")
        seed_targets.add(rows, "מנהלת מרפאה מכבי", "clinic_manager", "https://clinic.example.co.il/", "web")
        self.assertEqual(["נועה רז מנהלת מרפאה"], [row["name"] for row in rows])

    def test_clinic_manager_discovery_extracts_a_named_person_only(self):
        name,evidence=seed_targets.clinic_manager_person(
            'ד״ר נועה רז מונתה למנהלת המרפאה',
            'ד״ר נועה רז, מומחית ברפואת משפחה, מונתה למנהלת המרפאה של כללית בעיר.',
        )
        self.assertEqual("נועה רז",name)
        self.assertIn("מנהלת המרפאה",evidence)
        self.assertEqual(("",""),seed_targets.clinic_manager_person("מרפאת פתח תקווה","שעות פתיחה וטלפון"))
        rows=[]
        seed_targets.add(rows,name,"clinic_manager","https://clalit.example/clinic","web",role_evidence=evidence)
        self.assertEqual(1,len(rows))

    def test_clinic_manager_page_extracts_every_nearby_named_manager(self):
        people=seed_targets.clinic_manager_people(
            "מרפאות מומחים",
            'מנהל המרפאה: ד״ר שי גור. מידע למטופלים. מנהלת מרפאת העור: ד"ר יוליה ולדמן-גרינשפון.',
        )
        self.assertEqual(["שי גור","יוליה ולדמן-גרינשפון"],[name for name,_ in people])
        self.assertTrue(all("מרפא" in evidence for _,evidence in people))
        people=seed_targets.clinic_manager_people("צוות המרפאה",'מנהל המרפאה: ד"ר שי גור. ד"ר דרור וייס סגן מנהל המרפאה וראש צוות. ד"ר מעינית סיגלר.')
        self.assertEqual(["שי גור"],[name for name,_ in people])


if __name__ == "__main__":
    unittest.main()
