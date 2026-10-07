# Caregiver Care Binder: page content = t4 v1 with the t5 compliance edits applied (A1-A14, B0-B10, C1, C2, D).
# Block types: ("f", [labels]) fill-in lines · ("c", label, [options]) checkboxes · ("t", headers, rows, prefill)
#              ("h", text) subheading · ("p", text) · ("n", [items]) numbered · ("b", [items]) bullets
#              ("box", title, text) boxed note · ("lines", None) ruled lines to the bottom

SECTIONS = {
    "0": "FRONT MATTER", "1": "CARE SNAPSHOT", "2": "CARE TEAM & EMERGENCY CONTACTS", "3": "MEDICATIONS",
    "4": "APPOINTMENTS", "5": "DAILY CARE & OBSERVATION", "6": "INSURANCE, BENEFITS & LEGAL DOCUMENTS",
    "7": "HAND-OFF & RESPITE", "8": "FAMILY TASK-SHARING", "9": "CAREGIVER SELF-CARE", "10": "BACK MATTER",
}

C1 = ("This binder is an information organizer only. It does not provide medical, legal or financial advice, and it does "
      "not replace the instructions of a doctor, nurse, pharmacist, attorney or financial professional. Always follow the "
      "guidance of the licensed professionals involved in the person's care, and ask them if you are unsure about anything "
      "you record here. The seller has not reviewed or verified any information you enter. "
      "In an emergency, call your local emergency services immediately.")
C2 = ("An information organizer only. Not medical, legal or financial advice. Consult licensed professionals. "
      "In an emergency, call local emergency services.")
PRIVACY = ("Once filled in, this binder holds sensitive personal and health information. Store printed copies somewhere "
           "secure, such as a locked drawer or a place only trusted people can reach. If you save or fill in the PDF "
           "digitally, keep it on a password-protected device or account, and be careful when emailing or sharing it. "
           "Share it only with people involved in the person's care. Shred old pages you no longer need. Do not write "
           "account numbers, passwords or ID numbers in this binder.")
EMERGENCY = "In an emergency, call your local emergency number first."
MED_TABLE = ["Medication name", "Dose as prescribed (copy from label)", "Prescriber", "Pharmacy", "Refill date", "Notes"]
APPT_TABLE = ["Date", "Time", "Provider / clinic", "Purpose (as scheduled)", "Who is going", "Transport? (Y/N)", "Bring / prepare", "Done"]

VISIT = [
    ("h", "Before the visit"),
    ("f", ["Date", "Provider", "Clinic", "Reason for visit", "Changes noticed since last visit (see page 22)"]),
    ("p", "My questions (see the prompts on page 18):"),
    ("f", ["1.", "2.", "3.", "4."]),
    ("c", "Bring:", ["This binder", "Medication list", "Insurance card", "ID", "Recent logs", "Other: ______"]),
    ("h", "During / after the visit"),
    ("f", ["What the provider said (in their words)", "", "New or changed medications (copy instructions as given)", "",
           "Tests or referrals ordered", "Next appointment", "Follow-up tasks", "Assigned to"]),
    ("c", "Updated:", ["Medication list", "Appointment tracker"]),
]

PAGES = [
    # code, title, instruction, blocks
    ("0.1", "Cover", None, "COVER"),
    ("0.2", "How to Use This Binder",
     "This binder helps you keep care details organized and easy to share. Fill in what applies, and skip what doesn't.", [
         ("h", "Start here"),
         ("n", ["Fill in Section 1 (Care Snapshot) and Section 2 (Contacts) first. These are the pages others need most.",
                "Copy medication details exactly from pharmacy labels or prescriber instructions into Section 3. This list "
                "is a record only. It does not replace the label or your pharmacist's or prescriber's instructions.",
                "Bring the binder to appointments, and use the Visit Notes pages in Section 4.",
                "Use the Daily Care Log (Section 5) to note what you see, in your own words. You can share it with the "
                "care team if it helps.",
                "In Section 6, record where important documents are kept. Do not write account numbers, passwords or "
                "document contents in this binder.",
                "Before handing over care, fill in the Hand-Off Sheet (Section 7).",
                "Use Section 8 to share tasks with family. Use Section 9 to check in on yourself."]),
         ("h", "Good habits"),
         ("b", ["Use pencil for anything that changes often.", "Date every entry.",
                "Review the binder once a month, and log it on page 35.",
                "Keep the binder somewhere safe but easy to find. Tell one other person where it is. See the privacy note below."]),
         ("box", "Important: please read", C1),
         ("box", "Keep this binder private", PRIVACY),
     ]),
    ("1.1", "About the Person I Care For",
     "Basic details to share with new providers, helpers or family. Update when anything changes.", [
         ("f", ["Full name", "Preferred name", "Date of birth", "Address", "Phone", "Primary language"]),
         ("c", "Interpreter needed?", ["Yes", "No"]),
         ("c", "Lives:", ["Alone", "With family", "With partner", "Assisted living", "Care home", "Other: ______"]),
         ("f", ["Primary caregiver", "Relationship / phone", "Secondary caregiver", "Relationship / phone"]),
         ("h", "Health details as recorded by their care team (copy from provider paperwork)"),
         ("f", ["Diagnoses / conditions listed by providers", "",
                "Allergies (as listed by providers or pharmacy) and reaction noted", ""]),
         ("c", "Mobility aids used:", ["Cane", "Walker", "Wheelchair", "None", "Other: ______"]),
         ("c", "Devices:", ["Hearing aids", "Glasses", "Dentures", "Other: ______"]),
         ("f", ["Where devices are kept", "Last updated"]),
     ]),
    ("1.2", "Daily Routine & Preferences",
     "What a good day looks like for them. This helps anyone stepping in keep things familiar.", [
         ("t", ["Time of day", "Usual routine", "Notes / preferences"], 5, ["Morning", "Midday", "Afternoon", "Evening", "Night"]),
         ("f", ["Wake-up time", "Bedtime", "Meal preferences / dislikes", "Dietary instructions from care team (copy as given)",
                "Favorite activities, shows, music", "Things that comfort them", "Things that upset or worry them",
                "Faith / cultural practices to respect", "Pets and their care", "Other things to know"]),
     ]),
    ("2.1", "Emergency Contacts & Quick Info",
     "Keep this page at the front. Anyone helping in a hurry should be able to use it.", [
         ("f", ["Your local emergency number"]),
         ("h", "Emergency contacts"),
         ("t", ["Name", "Relationship", "Mobile", "Other phone", "Can make decisions? (Y/N, per documents on file)"], 5, None),
         ("h", "Quick info for responders"),
         ("f", ["Name", "Date of birth", "Address and access notes (gate code, key location)", "Primary doctor / phone",
                "Preferred hospital", "Allergies (as listed by providers)"]),
         ("p", "Current medication list: page 9 · Legal documents index: page 24"),
         ("f", ["Location of any medical orders on file (as kept by family)"]),
     ]),
    ("2.2", "Healthcare Providers", "List every doctor, specialist and clinic involved in their care.", [
         ("t", ["Name", "Specialty / role", "Clinic / practice", "Phone", "Fax / portal", "Address", "Last visit"], 8, None),
         ("c", "Patient portal used?", ["Yes", "No"]),
         ("f", ["Portal name", "Login details kept at (a location, never the password)"]),
     ]),
    ("2.3", "Pharmacy, Home Care & Services",
     "Pharmacies, home care, therapy, equipment suppliers, transport, meal services.", [
         ("t", ["Service", "Company / person", "Contact name", "Phone", "Email / website", "Schedule / days", "Notes"], 8,
          ["Pharmacy", "Home care agency", "Therapy", "Medical equipment", "Transport", "Meal delivery", "Cleaning / home help", "Other"]),
     ]),
    ("2.4", "Family, Friends & Neighbors", "The people in their circle. Note who can help, and how.", [
         ("t", ["Name", "Relationship", "Phone", "Email", "Lives nearby? (Y/N)", "Can help with", "Best times"], 10, None),
         ("f", ["Neighbor with a spare key", "Phone"]),
     ]),
    ("3.1", "Current Medication List",
     "Copy each medication exactly as written on the pharmacy label or prescriber instructions, including over-the-counter "
     "products, vitamins and supplements. This list is a record only. Do not change any medication based on this binder: "
     "ask the prescriber or pharmacist.", [
         ("t", MED_TABLE, 10, None),
         ("f", ["List last checked with pharmacist or prescriber on", "By"]),
     ]),
    ("3.2", "Current Medication List (continued)", "Continue your list here. Use the same columns.", [("t", MED_TABLE, 12, None)]),
    ("3.3", "Medication Change Record",
     "Record any medication that is started, stopped or changed, and who made the change. This keeps a clear history for the care team.", [
         ("t", ["Date", "Medication", "Started / stopped / changed", "What changed (as instructed)", "Changed by (prescriber name)",
                "Reason given by prescriber", "List updated? (✓)"], 12, None),
     ]),
    ("3.4", "Refill Tracker", "Track refill dates so nothing runs out.", [
         ("t", ["Medication", "Pharmacy", "Rx number (optional)", "Refills remaining", "Next refill due", "Ordered on", "Picked up / delivered on"], 12, None),
         ("c", "Pharmacy auto-refill set up?", ["Yes", "No"]),
         ("c", "Delivery arranged?", ["Yes", "No"]),
     ]),
    ("3.5", "Daily Medication Checklist",
     "Reprint as needed. Write each medication and time exactly as on the label, then tick when given. This is a record "
     "only, not a dosing guide. If a dose is missed or you're unsure, follow the label or call the pharmacist or prescriber.", [
         ("f", ["Week of"]),
         ("t", ["Medication & time (as on label)", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Initials"], 10, None),
         ("p", "Key: ✓ given · R refused · M missed · H held as instructed by provider"),
         ("f", ["Notes for the care team", ""]),
     ]),
    ("4.1", "Appointment Tracker", "List upcoming appointments, tests and follow-ups in one place.", [("t", APPT_TABLE, 12, None)]),
    ("4.2", "Appointment Tracker (continued)", "Continue your list here.", [("t", APPT_TABLE, 14, None)]),
    ("4.3", "Visit Notes", "Reprint as needed. Fill in the top before the visit and the bottom during or after it.", VISIT),
    ("4.4", "Visit Notes (extra copy)", "Reprint as needed. Fill in the top before the visit and the bottom during or after it.", VISIT),
    ("4.5", "Questions to Ask: Prompt Bank",
     "Prompts to help you get clear information. Choose the ones that fit, and copy them onto your Visit Notes page.", [
         ("h", "About the visit"),
         ("b", ["What is the main thing we should know from today?", "Could you write that down or print it for us?",
                "Who should we contact with questions after today?", "What is the best way to reach you or your office?"]),
         ("h", "About medications"),
         ("b", ["What is this medication for?", "How and when should it be taken, exactly?",
                "Is there anything we should watch for and report to you?", "Does this change anything else on the current list?"]),
         ("h", "About tests and referrals"),
         ("b", ["What is this test or referral for?", "How and when will we get the results?", "Is there anything to do to prepare?"]),
         ("h", "About next steps"),
         ("b", ["When should we come back?", "What should we contact you about before then?",
                "Who do we call after hours?", "Are there services or resources you recommend we ask about?"]),
         ("h", "About paperwork"),
         ("b", ["Are there forms we need to complete or bring next time?", "Can visit notes be shared through the patient portal?"]),
     ]),
    ("4.6", "Hospital & Urgent Visit Record", "Keep a record of emergency room visits, hospital stays and urgent care.", [
         ("t", ["Date in", "Date out", "Hospital / facility", "Reason (as stated by facility)", "Discharge papers kept at",
                "Follow-up needed", "Follow-up booked? (Y/N)"], 6, None),
         ("f", ["Hospital bag kept at", "Items to pack (your checklist)", "", ""]),
     ]),
    ("5.1", "Daily Care Log",
     "Reprint as needed. Note what you see and what was done. Facts only. This log is a record to share with the care team, "
     "not a way to assess health.", [
         ("f", ["Date", "Logged by"]),
         ("t", ["Area", "Morning", "Afternoon", "Evening", "Night"], 8,
          ["Meals / fluids", "Medications given (see page 13)", "Personal care", "Toileting", "Activity / mobility",
           "Mood (as observed)", "Sleep / rest", "Visitors / calls"]),
         ("f", ["Anything unusual today", "", "Shared with", "Time"]),
     ]),
    ("5.2", "Weekly Observation Summary", "Reprint as needed. A quick weekly snapshot, handy before appointments.", [
         ("f", ["Week of"]),
         ("t", ["Area", "How the week went (in your words)", "Same / different from last week"], 7,
          ["Eating & drinking", "Sleep", "Mood & engagement", "Getting around", "Personal care", "Memory & communication", "Social contact"]),
         ("f", ["Questions to raise at the next appointment", "", "Bring to (provider / date)"]),
     ]),
    ("5.3", "Changes Noticed Record",
     "Record any change you notice, and who you told. This creates a clear timeline for the care team. If you are worried, "
     "contact their provider, or your local emergency number in an emergency.", [
         ("t", ["Date & time", "What changed (in your words)", "Told to (provider) / date", "How (call / portal / in person)",
                "What they said", "Follow-up"], 10, None),
     ]),
    ("6.1", "Insurance & Benefits Index",
     "Record what coverage exists and where the paperwork is kept. Do not write policy numbers, member IDs or login details here.", [
         ("t", ["Type of coverage / benefit", "Provider / agency", "Phone", "Where card / paperwork is kept", "Who has access", "Renewal / review date"], 8,
          ["Health insurance", "Supplemental / secondary", "Prescription coverage", "Dental / vision", "Long-term care",
           "Pension / retirement income", "Government benefits", "Other"]),
     ]),
    ("6.2", "Legal Documents Index",
     "Record which documents exist and where they are kept. Do not copy their contents here. This page lists where documents "
     "are kept. It is not a legal document and does not replace advice from a licensed attorney.", [
         ("t", ["Document", "Exists? (Y / N / unsure)", "Date signed", "Where original is kept", "Copies held by", "Professional who prepared it"], 10,
          ["Will", "Power of attorney (financial)", "Healthcare proxy", "Advance directive / living will", "Medical orders on file",
           "Guardianship papers", "Trust documents", "Funeral / burial arrangements", "Organ donation record", "Other"]),
     ]),
    ("6.3", "Financial & Household Accounts Index",
     "A map of accounts and bills, showing where statements are kept and who manages them. Never write account numbers, PINs or passwords here.", [
         ("t", ["Account / bill", "Institution / company", "How paid (auto / manual)", "Where statements are kept", "Who manages it", "Due date / frequency"], 10,
          ["Bank account", "Credit card", "Rent / mortgage", "Property tax", "Utilities", "Phone / internet", "Home insurance",
           "Care / agency fees", "Subscriptions", "Other"]),
         ("f", ["Password list kept by (a person, never the passwords)"]),
     ]),
    ("6.4", "Who Holds What: Copies & Keys", "A quick map of who has keys, copies and access.", [
         ("t", ["Item", "Location", "Who has a copy / key", "Contact"], 9,
          ["House keys", "Car keys", "Safe / lockbox", "Safe deposit box", "Mailbox", "Copy of this binder", "ID documents",
           "Medical records copies", "Other"]),
     ]),
    ("7.1", "Hand-Off Sheet: Today's Essentials",
     "Fill this in before handing over care to a sibling, friend or substitute caregiver. Pages 27-28 can be handed over on their own. "
     + EMERGENCY, [
         ("f", ["Caring for", "Date(s)", "From / to", "Main contact while I'm away / phone", "Backup contact / phone",
                "Medications are kept"]),
         ("p", "Emergency contacts & quick info: page 5. Medications: follow the Daily Medication Checklist on page 13, exactly as on the labels."),
         ("h", "Today / this period"),
         ("t", ["Time", "What needs to happen", "Notes"], 8, None),
         ("f", ["Appointments during this period", "Things to watch for and report to me (our family's notes)"]),
     ]),
    ("7.2", "Hand-Off Sheet: Routines & Home", "Household and routine details for the person stepping in. " + EMERGENCY, [
         ("p", "Routine and preferences: see page 4."),
         ("f", ["Things that help them feel settled", "Things to avoid", "Meals planned / food in the house",
                "Mobility / transfer notes from their care team (copy as given)", "Pets", "Wi-Fi network name",
                "Wi-Fi password kept at (a location)", "Thermostat, alarms, locks", "Trash / recycling days",
                "Helpers visiting during this period / times", "Our family's notes", ""]),
     ]),
    ("7.3", "Shift Handover Notes", "Reprint as needed. Use at every handover so nothing gets lost. " + EMERGENCY, [
         ("t", ["Date / time", "Handed over by", "Handed to", "What happened this shift", "Still to do", "Concerns shared with"], 6, None),
     ]),
    ("8.1", "Family Task-Sharing Grid",
     "Divide the work so no one carries it alone. Agree on tasks together and review them regularly.", [
         ("t", ["Task", "Who is responsible", "Backup", "How often", "Next due", "Status / notes"], 12,
          ["Appointments & transport", "Medications & refills", "Groceries & meals", "Bills & paperwork", "Housekeeping", "Laundry",
           "Visits & companionship", "Calls with care team", "Respite cover", "Updates to family", "Other", ""]),
     ]),
    ("8.2", "Weekly Coverage Calendar", "Reprint as needed. See at a glance who is covering when.", [
         ("f", ["Week of"]),
         ("t", ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], 4, ["Morning", "Afternoon", "Evening", "Overnight"]),
         ("f", ["Gaps to fill", "Notes", ""]),
     ]),
    ("8.3", "Family Meeting Notes", "Keep a simple record of family decisions and next steps.", [
         ("f", ["Date", "Attended", "Topic 1", "Topic 2", "Topic 3", "What we agreed", ""]),
         ("h", "Action items"),
         ("t", ["Action", "Who", "By when"], 6, None),
         ("f", ["Next meeting date"]),
     ]),
    ("9.1", "My Weekly Check-In",
     "Reprint as needed. Caring for someone else is easier when you check in with yourself too. A few minutes is enough.", [
         ("f", ["Week of"]),
         ("c", "This week, my energy has been:", ["Low", "Okay", "Good"]),
         ("c", "Sleep this week:", ["Poor", "Okay", "Good"]),
         ("f", ["One thing that went well", "One thing that was hard", "Something I did just for me",
                "Something I'd like help with", "Who I can ask", "One small thing I'll do for myself next week",
                "Someone I'd like to talk to this week"]),
         ("box", "", "If you are struggling, consider talking with your own doctor or a local support service. "
                     "If you or someone else is in danger, call your local emergency number."),
     ]),
    ("9.2", "My Support & Breaks Plan", "Plan your breaks before you need them.", [
         ("f", ["People I can call to talk", "People who can cover so I can take a break / phone", "Things that help me recharge"]),
         ("t", ["Break / time off", "When", "Who covers", "Booked? (Y/N)"], 5, None),
         ("f", ["Support groups or services I want to look into", "My own appointments I shouldn't skip"]),
         ("box", "", "If you are struggling, consider talking with your own doctor or a local support service. "
                     "If you or someone else is in danger, call your local emergency number."),
     ]),
    ("10.1", "Binder Review Record & Notes", "Review the binder monthly, or after any big change, and log it here.", [
         ("t", ["Date reviewed", "Reviewed by", "Pages updated", "Shared with"], 10, None),
         ("h", "Notes"),
         ("lines", None),
     ]),
]
assert len(PAGES) == 35
