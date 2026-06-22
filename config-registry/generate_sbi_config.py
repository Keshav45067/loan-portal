import yaml
import os

SBI_GRAPH = {
    "Q_START": {
        "type": "voice-qa",
        "text_template": "नमस्ते! मैं आपका एसबीआई बैंक बचत खाता फॉर्म भरने में आपकी मदद करूंगी। क्या हम शुरू करें?",
        "text_template_en": "Hello! I will help you fill out your SBI savings account form. Shall we start?",
        "text_template_te": "నమస్తే! నేను మీ ఎస్బిఐ బ్యాంక్ సేవింగ్స్ ఖాతా ఫారమ్‌ను పూరించడానికి మీకు సహాయం చేస్తాను. మనం ప్రారంభిద్దామా?",
        "targets": ["consent"],
        "edges": [{"condition": "always", "next": "DOC_AADHAAR_FRONT"}]
    },
    "DOC_AADHAAR_FRONT": {
        "type": "capture",
        "document_id": "aadhaar_front",
        "edges": [{"condition": "always", "next": "DOC_AADHAAR_BACK"}]
    },
    "DOC_AADHAAR_BACK": {
        "type": "capture",
        "document_id": "aadhaar_back",
        "edges": [{"condition": "always", "next": "Q_AADHAAR_CONFIRM"}]
    },
    "Q_AADHAAR_CONFIRM": {
        "type": "voice-qa",
        "text_template": "धन्यवाद! मैंने आपके आधार से आपका नाम {full_name}, जन्म तिथि {date_of_birth}, आधार नंबर जिसके अंत में {aadhaar_last_four} है, और लिंग {gender} दर्ज कर लिया है। क्या ये सभी विवरण सही हैं?",
        "text_template_en": "Thank you! I have recorded your name {full_name}, date of birth {date_of_birth}, Aadhaar number ending with {aadhaar_last_four}, and gender {gender} from your Aadhaar. Are all these details correct?",
        "text_template_te": "ధన్యవాదాలు! నేను మీ ఆధార్ నుండి మీ పేరు {full_name}, పుట్టిన తేదీ {date_of_birth}, {aadhaar_last_four} తో ముగిసే ఆధార్ నంబర్ మరియు లింగం {gender} నమోదు చేసుకున్నాను. ఈ వివరాలన్నీ సరైనవేనా?",
        "targets": ["aadhaar_confirmed"],
        "routing_prompt": "Evaluate if the user confirmed that their Aadhaar details (Name, DOB, Aadhaar number, gender) are correct. Set 'routing_decision' to 'YES' if they are correct/confirmed, 'NO' if the user says something is incorrect or wants to re-capture/retry.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "DOC_PAN"},
            {"condition": "routing_decision == 'NO'", "next": "DOC_AADHAAR_FRONT"},
            {"condition": "always", "next": "DOC_PAN"}
        ]
    },
    "DOC_PAN": {
        "type": "capture",
        "document_id": "pan",
        "edges": [{"condition": "always", "next": "Q_PAN_CONFIRM"}]
    },
    "Q_PAN_CONFIRM": {
        "type": "voice-qa",
        "text_template": "मैंने आपके पैन कार्ड से आपका पैन नंबर {pan_number} दर्ज कर लिया है। क्या आप पुष्टि करते हैं कि यह सही है?",
        "text_template_en": "I have recorded your PAN number {pan_number} from your PAN card. Do you confirm that this is correct?",
        "text_template_te": "నేను మీ పాన్ కార్డ్ నుండి మీ పాన్ నంబర్ {pan_number} నమోదు చేసుకున్నాను. ఇది సరైనదేనని మీరు ధృవీకరిస్తున్నారా?",
        "targets": ["pan_confirmed"],
        "routing_prompt": "Evaluate if the user confirmed that their PAN details/number are correct. Set 'routing_decision' to 'YES' if confirmed, 'NO' if they say it's wrong or want to retry.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "Q_OCCUPATION"},
            {"condition": "routing_decision == 'NO'", "next": "DOC_PAN"},
            {"condition": "always", "next": "Q_OCCUPATION"}
        ]
    },
    "Q_OCCUPATION": {
        "type": "voice-qa",
        "text_template": "आपका व्यवसाय या आजीविका का प्रकार क्या है? क्या आप राज्य सरकार (State Govt), केंद्र सरकार (Central govt), सार्वजनिक क्षेत्र (Public sector), रक्षा (defence), निजी क्षेत्र (Private sector) में कार्यरत हैं या आपका कोई व्यवसाय (Business) है?",
        "text_template_en": "What is your occupation or source of livelihood? Are you employed in State Govt, Central govt, Public sector, defence, Private sector, or do you have a Business?",
        "text_template_te": "మీ వృత్తి లేదా జీవనోపాధి రకం ఏమిటి? మీరు రాష్ట్ర ప్రభుత్వం, కేంద్ర ప్రభుత్వం, పబ్లిక్ సెక్టార్, రక్షణ రంగం, ప్రైవేట్ సెక్టార్‌లో పనిచేస్తున్నారా లేదా మీకు ఏదైనా వ్యాపారం ఉందా?",
        "targets": ["occupation_type"],
        "routing_prompt": "Identify the user's occupation type from these categories: 'Business', 'defence', 'Private sector', 'State Govt', 'Central govt', 'Public sector'. Set 'routing_decision' to: 'BUSINESS' if occupation type is Business, 'DEFENCE' if occupation type is defence, 'PRIVATE' if occupation type is Private sector, 'GOVT' if occupation type is State Govt, Central govt, or Public sector.",
        "edges": [
            {"condition": "routing_decision == 'BUSINESS'", "next": "Q_BUSINESS_DETAILS"},
            {"condition": "routing_decision == 'DEFENCE'", "next": "Q_PLACE_OF_POSTING"},
            {"condition": "routing_decision == 'PRIVATE'", "next": "Q_EMPLOYEE_ID"},
            {"condition": "routing_decision == 'GOVT'", "next": "Q_EMPLOYEE_ID"},
            {"condition": "always", "next": "Q_EMPLOYEE_ID"}
        ]
    },
    "Q_EMPLOYEE_ID": {
        "type": "voice-qa",
        "text_template": "कृपया अपना कर्मचारी आईडी (Employee ID) बताएं।",
        "text_template_en": "Please tell me your Employee ID.",
        "text_template_te": "దయచేసి మీ ఉద్యోగి ఐడి (Employee ID) చెప్పండి.",
        "targets": ["employee_id"],
        "edges": [{"condition": "always", "next": "Q_PLACE_OF_POSTING"}]
    },
    "Q_PLACE_OF_POSTING": {
        "type": "voice-qa",
        "text_template": "आपकी पोस्टिंग का स्थान (Place of Posting) क्या है?",
        "text_template_en": "What is your place of posting?",
        "text_template_te": "మీ పోస్టింగ్ స్థలం ఏమిటి?",
        "targets": ["place_of_posting"],
        "edges": [
            {"condition": "occupation_type == 'Private sector'", "next": "Q_COMPANY_AND_DESIGNATION"},
            {"condition": "always", "next": "Q_AADHAAR_AS_ADDRESS_PROOF"}
        ]
    },
    "Q_COMPANY_AND_DESIGNATION": {
        "type": "voice-qa",
        "text_template": "कृपया अपनी कंपनी का नाम और अपना पद (Designation) बताएं।",
        "text_template_en": "Please tell me your company name and designation.",
        "text_template_te": "దయచేసి మీ కంపెనీ పేరు మరియు మీ హోదా చెప్పండి.",
        "targets": ["company_name", "designation"],
        "edges": [{"condition": "always", "next": "Q_AADHAAR_AS_ADDRESS_PROOF"}]
    },
    "Q_BUSINESS_DETAILS": {
        "type": "voice-qa",
        "text_template": "आपके व्यवसाय की प्रकृति (Nature of Business) और व्यवसाय का प्रकार (Type of Business) क्या है? (जैसे: मैन्युफैक्चरिंग, सर्विस, रीटेल ट्रेड, या होलसेल ट्रेड)",
        "text_template_en": "What is the nature of your business and type of business? (for example Manufacturing, Service, Retail Trade, or Wholesale Trade)",
        "text_template_te": "మీ వ్యాపార స్వభావం మరియు వ్యాపార రకం ఏమిటి? (ఉదాహరణకు: తయారీ, సేవ, రిటైల్ వ్యాపారం లేదా హోల్‌సేల్ వ్యాపారం)",
        "targets": ["nature_of_business", "type_of_business"],
        "edges": [{"condition": "always", "next": "Q_AADHAAR_AS_ADDRESS_PROOF"}]
    },
    "Q_AADHAAR_AS_ADDRESS_PROOF": {
        "type": "voice-qa",
        "text_template": "क्या आप अपने आधार कार्ड का उपयोग पते के प्रमाण (Address Proof) के रूप में करना चाहते हैं?",
        "text_template_en": "Do you want to use your Aadhaar card as address proof?",
        "text_template_te": "మీరు మీ ఆధార్ కార్డ్‌ను పతే ప్రూఫ్ (చిరునామా రుజువు) గా ఉపయోగించాలనుకుంటున్నారా?",
        "targets": ["use_aadhaar_as_address_proof"],
        "routing_prompt": "Evaluate if the user wants to use their Aadhaar as address proof. Set 'routing_decision' to 'YES' if they want to use Aadhaar, 'NO' if not.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "Q_CORRESPONDENCE_SAME"},
            {"condition": "routing_decision == 'NO'", "next": "Q_SELECT_ADDRESS_PROOF_DOC"},
            {"condition": "always", "next": "Q_CORRESPONDENCE_SAME"}
        ]
    },
    "Q_SELECT_ADDRESS_PROOF_DOC": {
        "type": "voice-qa",
        "text_template": "आप पते के प्रमाण के लिए कौन सा दस्तावेज़ देना चाहेंगे? (जैसे: वोटर आईडी, ड्राइविंग लाइसेंस, पासपोर्ट या नरेगा जॉब कार्ड)",
        "text_template_en": "Which document would you like to provide for address proof? (for example Voter ID, Driving License, Passport, or NREGA Job Card)",
        "text_template_te": "చిరునామా రుజువు కోసం మీరు ఏ పత్రాన్ని ఇవ్వాలనుకుంటున్నారు? (ఉదాహరణకు: ఓటర్ ఐడి, డ్రైవింగ్ లైసెన్స్, పాస్‌పోర్ట్ లేదా ఉపాధి హామీ జాబ్ కార్డ్)",
        "targets": ["address_proof_document_type"],
        "routing_prompt": "Evaluate if the document selected by the user is a valid official address proof (such as Voter ID, Driving License, Passport, NREGA Job Card). Set 'routing_decision' to 'YES' if it is valid, 'NO' if it is invalid/not accepted.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "DOC_ADDRESS_PROOF_CAPTURE"},
            {"condition": "routing_decision == 'NO'", "next": "Q_INVALID_ADDRESS_PROOF_DOC"},
            {"condition": "always", "next": "DOC_ADDRESS_PROOF_CAPTURE"}
        ]
    },
    "Q_INVALID_ADDRESS_PROOF_DOC": {
        "type": "voice-qa",
        "text_template": "माफ कीजियेगा, यह पते के प्रमाण के रूप में मान्य नहीं है। कृपया वोटर आईडी, ड्राइविंग लाइसेंस या पासपोर्ट जैसे मान्य दस्तावेज़ का नाम बताएं।",
        "text_template_en": "Sorry, this is not valid as address proof. Please specify a valid document like Voter ID, Driving License, or Passport.",
        "text_template_te": "క్షమించండి, ఇది చిరునామా రుజువుగా చెల్లదు. దయచేసి ఓటర్ ఐడి, డ్రైవింగ్ లైసెన్స్ లేదా పాస్‌పోర్ట్ వంటి చెల్లుబాటు అయ్యే పత్రం పేరు చెప్పండి.",
        "targets": ["address_proof_document_type"],
        "routing_prompt": "Evaluate if the document selected by the user is a valid official address proof. Set 'routing_decision' to 'YES' if valid, 'NO' if invalid.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "DOC_ADDRESS_PROOF_CAPTURE"},
            {"condition": "routing_decision == 'NO'", "next": "Q_INVALID_ADDRESS_PROOF_DOC"},
            {"condition": "always", "next": "DOC_ADDRESS_PROOF_CAPTURE"}
        ]
    },
    "DOC_ADDRESS_PROOF_CAPTURE": {
        "type": "capture",
        "document_id": "address_proof",
        "edges": [{"condition": "always", "next": "Q_ADDRESS_PROOF_CONFIRM"}]
    },
    "Q_ADDRESS_PROOF_CONFIRM": {
        "type": "voice-qa",
        "text_template": "मैंने आपके पते के दस्तावेज़ से पते का विवरण दर्ज कर लिया है। क्या आप पुष्टि करते हैं कि यह विवरण सही है?",
        "text_template_en": "I have recorded the address details from your address document. Do you confirm that these details are correct?",
        "text_template_te": "నేను మీ చిరునామా పత్రం నుండి చిరునామా వివరాలను నమోదు చేసుకున్నాను. ఈ వివరాలు సరైనవేనని మీరు ధృవీకరిస్తున్నారా?",
        "targets": ["address_proof_confirmed"],
        "routing_prompt": "Evaluate if the user confirmed that the address details extracted from the document are correct. Set 'routing_decision' to 'YES' if correct/confirmed, 'NO' if they say it is incorrect or want to retry.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "Q_CORRESPONDENCE_SAME"},
            {"condition": "routing_decision == 'NO'", "next": "DOC_ADDRESS_PROOF_CAPTURE"},
            {"condition": "always", "next": "Q_CORRESPONDENCE_SAME"}
        ]
    },
    "Q_CORRESPONDENCE_SAME": {
        "type": "voice-qa",
        "text_template": "क्या आपका वर्तमान पत्राचार का पता (Correspondence Address) आपके स्थायी पते के समान ही है?",
        "text_template_en": "Is your current correspondence address the same as your permanent address?",
        "text_template_te": "మీ ప్రస్తుత చిరునామా (పత్రాచార చిరునామా) మీ శాశ్వత చిరునామాతో సమానంగా ఉందా?",
        "targets": ["correspondence_address_same"],
        "routing_prompt": "Evaluate if the user's correspondence address is the SAME as their current address. Set 'routing_decision' to 'YES' if it is the same, 'NO' if it is different.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "Q_FATHER_NAME"},
            {"condition": "routing_decision == 'NO'", "next": "Q_SELECT_CORRESPONDENCE_DOC"},
            {"condition": "always", "next": "Q_FATHER_NAME"}
        ]
    },
    "Q_SELECT_CORRESPONDENCE_DOC": {
        "type": "voice-qa",
        "text_template": "पत्राचार के पते के लिए आप कौन सा दस्तावेज़ देना चाहेंगे?",
        "text_template_en": "Which document would you like to provide for correspondence address proof?",
        "text_template_te": "పత్రాచార చిరునామా కోసం మీరు ఏ పత్రాన్ని ఇవ్వాలనుకుంటున్నారు?",
        "targets": ["correspondence_document_type"],
        "routing_prompt": "Evaluate if the document selected by the user is a valid correspondence address proof. Set 'routing_decision' to 'YES' if valid, 'NO' if invalid.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "DOC_CORRESPONDENCE_CAPTURE"},
            {"condition": "routing_decision == 'NO'", "next": "Q_INVALID_CORRESPONDENCE_DOC"},
            {"condition": "always", "next": "DOC_CORRESPONDENCE_CAPTURE"}
        ]
    },
    "Q_INVALID_CORRESPONDENCE_DOC": {
        "type": "voice-qa",
        "text_template": "यह दस्तावेज़ पत्राचार के पते के रूप में स्वीकार्य नहीं है। कृपया कोई अन्य मान्य दस्तावेज़ बताएं।",
        "text_template_en": "This document is not acceptable as correspondence address proof. Please specify another valid document.",
        "text_template_te": "ఈ పత్రం పత్రాచార చిరునామాగా అంగీకరించబడదు. దయచేసి మరొక చెల్లుబాటు అయ్యే పత్రాన్ని చెప్పండి.",
        "targets": ["correspondence_document_type"],
        "routing_prompt": "Evaluate if the document selected by the user is valid. Set 'routing_decision' to 'YES' if valid, 'NO' if invalid.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "DOC_CORRESPONDENCE_CAPTURE"},
            {"condition": "routing_decision == 'NO'", "next": "Q_INVALID_CORRESPONDENCE_DOC"},
            {"condition": "always", "next": "DOC_CORRESPONDENCE_CAPTURE"}
        ]
    },
    "DOC_CORRESPONDENCE_CAPTURE": {
        "type": "capture",
        "document_id": "correspondence_proof",
        "edges": [{"condition": "always", "next": "Q_CORRESPONDENCE_CONFIRM"}]
    },
    "Q_CORRESPONDENCE_CONFIRM": {
        "type": "voice-qa",
        "text_template": "मैंने आपके दस्तावेज़ से पत्राचार पते का विवरण दर्ज कर लिया है। क्या आप पुष्टि करते हैं कि यह सही है?",
        "text_template_en": "I have recorded the correspondence address details from your document. Do you confirm that this is correct?",
        "text_template_te": "నేను మీ పత్రం నుండి పత్రాచార చిరునామా వివరాలను నమోదు చేసుకున్నాను. ఇది సరైనదేనని మీరు ధృవీకరిస్తున్నారా?",
        "targets": ["correspondence_confirmed"],
        "routing_prompt": "Evaluate if the user confirmed that the correspondence address details are correct. Set 'routing_decision' to 'YES' if confirmed, 'NO' if not.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "Q_FATHER_NAME"},
            {"condition": "routing_decision == 'NO'", "next": "DOC_CORRESPONDENCE_CAPTURE"},
            {"condition": "always", "next": "Q_FATHER_NAME"}
        ]
    },
    "Q_FATHER_NAME": {
        "type": "voice-qa",
        "text_template": "कृपया मुझे अपने पिता का पूरा नाम बताएं।",
        "text_template_en": "Please tell me your father's full name.",
        "text_template_te": "దయచేసి మీ తండ్రి పూర్తి పేరు చెప్పండి.",
        "targets": ["father_name"],
        "edges": [{"condition": "always", "next": "Q_MOBILE"}]
    },
    "Q_MOBILE": {
        "type": "voice-qa",
        "text_template": "आपका संपर्क मोबाइल नंबर क्या है?",
        "text_template_en": "What is your contact mobile number?",
        "text_template_te": "మీ సంప్రదింపు మొబైల్ నంబర్ ఏమిటి?",
        "targets": ["mobile_number"],
        "edges": [{"condition": "always", "next": "Q_EMAIL"}]
    },
    "Q_EMAIL": {
        "type": "voice-qa",
        "text_template": "आपकी ईमेल आईडी क्या है?",
        "text_template_en": "What is your email ID?",
        "text_template_te": "మీ ఈమెయిల్ ఐడి ఏమిటి?",
        "targets": ["email_id"],
        "edges": [{"condition": "always", "next": "Q_MARITAL"}]
    },
    "Q_MARITAL": {
        "type": "voice-qa",
        "text_template": "आपकी वैवाहिक स्थिति (Marital Status) क्या है? (विवाहित या अविवाहित)",
        "text_template_en": "What is your marital status? (Married or Unmarried)",
        "text_template_te": "మీ వైవాహిక స్థితి ఏమిటి? (వివాహం లేదా అవివాహితులు)",
        "targets": ["marital_status"],
        "edges": [{"condition": "always", "next": "Q_FAMILY_MEMBERS"}]
    },
    "Q_FAMILY_MEMBERS": {
        "type": "voice-qa",
        "text_template": "आपके परिवार में कुल कितने सदस्य हैं?",
        "text_template_en": "How many members are there in your family in total?",
        "text_template_te": "మీ కుటుంబంలో మొత్తం ఎంతమంది సభ్యులు ఉన్నారు?",
        "targets": ["number_of_family_members"],
        "edges": [{"condition": "always", "next": "Q_EDUCATION"}]
    },
    "Q_EDUCATION": {
        "type": "voice-qa",
        "text_template": "आपकी शैक्षणिक योग्यता (Educational Qualification) क्या है? (जैसे: 10वीं पास, 12वीं पास, स्नातक या स्नातकोत्तर)",
        "text_template_en": "What is your educational qualification? (for example 10th pass, 12th pass, Graduate, or Post Graduate)",
        "text_template_te": "మీ విద్యా అర్హత ఏమిటి? (ఉదాహరణకు: 10వ తరగతి, 12వ తరగతి, డిగ్రీ లేదా పీజీ)",
        "targets": ["educational_qualification"],
        "edges": [{"condition": "always", "next": "Q_SOURCES_OF_INCOME"}]
    },
    "Q_SOURCES_OF_INCOME": {
        "type": "voice-qa",
        "text_template": "आपकी आय के स्रोत (Sources of income) क्या-क्या हैं? (जैसे: वेतन, व्यापार, कृषि, पेंशन या किराया)",
        "text_template_en": "What are your sources of income? (for example Salary, Business, Agriculture, Pension, or Rent)",
        "text_template_te": "మీ ఆదాయ వనరులు ఏమిటి? (ఉదాహరణకు: జీతం, వ్యాపారం, వ్యవసాయం, పెన్షన్ లేదా అద్దె)",
        "targets": ["sources_of_income"],
        "edges": [{"condition": "always", "next": "Q_ANNUAL_INCOME"}]
    },
    "Q_ANNUAL_INCOME": {
        "type": "voice-qa",
        "text_template": "आपकी वर्तमान वार्षिक आय (Current Annual Income) लगभग कितनी है?",
        "text_template_en": "Approximately how much is your current annual income?",
        "text_template_te": "మీ ప్రస్తుత వార్షిక ఆదాయం సుమారుగా ఎంత?",
        "targets": ["annual_income"],
        "edges": [{"condition": "always", "next": "Q_NET_WORTH"}]
    },
    "Q_NET_WORTH": {
        "type": "voice-qa",
        "text_template": "की कुल संपत्ति या नेट वर्थ (Current Net Worth) कितनी है?",
        "text_template_en": "What is your total assets or current net worth?",
        "text_template_te": "మీ మొత్తం ఆస్తులు లేదా ప్రస్తుత నికర విలువ ఎంత?",
        "targets": ["net_worth"],
        "edges": [{"condition": "always", "next": "Q_RELIGION"}]
    },
    "Q_RELIGION": {
        "type": "voice-qa",
        "text_template": "आपका धर्म (Religion) क्या है?",
        "text_template_en": "What is your religion?",
        "text_template_te": "మీ మతం ఏమిటి?",
        "targets": ["religion"],
        "edges": [{"condition": "always", "next": "Q_CASTE"}]
    },
    "Q_CASTE": {
        "type": "voice-qa",
        "text_template": "आपकी श्रेणी या जाति वर्ग (Caste Category) कौन सा है - जनरल (General), ओबीसी (OBC), एससी (SC) या एसटी (ST)?",
        "text_template_en": "Which is your caste category - General, OBC, SC, or ST?",
        "text_template_te": "మీ కుల వర్గం ఏది - జనరల్, ఓబిసి, ఎస్సీ లేదా ఎస్టీ?",
        "targets": ["caste_category"],
        "edges": [{"condition": "always", "next": "END"}]
    },
    "END": {
        "type": "voice-qa",
        "text_template": "धन्यवाद! आपके बचत खाता खोलने के फॉर्म की सभी आवश्यक जानकारी दर्ज कर ली गई है। आपका दिन शुभ हो।",
        "text_template_en": "Thank you! All the necessary information for your savings account opening form has been recorded. Have a nice day.",
        "text_template_te": "ధన్యవాదాలు! మీ సేవింగ్స్ ఖాతా తెరవడానికి అవసరమైన సమాచారం అంతా నమోదు చేయబడింది. మీకు మంచి రోజు అవ్వాలి.",
        "targets": [],
        "edges": []
    }
}

FIELD_INSTRUCTIONS = {
    "consent": "INFER as 'Yes' or 'No'. Whether the user has given explicit consent to start filling the form.",
    "aadhaar_confirmed": "INFER as 'Yes' or 'No'. Whether the user confirmed that their Aadhaar details are correct.",
    "pan_confirmed": "INFER as 'Yes' or 'No'. Whether the user confirmed their PAN details are correct.",
    "occupation_type": "INFER as one of: 'State Govt', 'Central govt', 'Public sector', 'defence', 'Private sector', 'Business'.",
    "employee_id": "EXTRACT the employee ID if provided. If not applicable, value is 'None'.",
    "place_of_posting": "EXTRACT the place or city of posting.",
    "company_name": "EXTRACT the name of the employer company.",
    "designation": "EXTRACT the user's designation or job title.",
    "nature_of_business": "EXTRACT the nature/activity of the business in English (such as Kirana Shop, Dairy, Tailoring, Food Processing, Manufacturing, etc.).",
    "type_of_business": "INFER as one of: 'Manufacturing', 'Services', 'Retail Trade', 'Wholesale Trade'.",
    "use_aadhaar_as_address_proof": "INFER as 'Yes' or 'No'. Whether Aadhaar should be used as address proof.",
    "address_proof_document_type": "INFER the document type chosen by the user for address proof (such as Voter ID, Driving License, Passport, NREGA Job Card).",
    "address_proof_confirmed": "INFER as 'Yes' or 'No'. Whether the user confirmed their address proof details are correct.",
    "correspondence_address_same": "INFER as 'Yes' or 'No'. Whether correspondence address is same as current/permanent address.",
    "correspondence_document_type": "INFER the document type chosen by the user for correspondence address proof.",
    "correspondence_confirmed": "INFER as 'Yes' or 'No'. Whether the user confirmed their correspondence address details.",
    "father_name": "EXTRACT the full name of the user's father.",
    "mobile_number": "EXTRACT the user's 10-digit mobile number.",
    "email_id": "EXTRACT the user's email address.",
    "marital_status": "INFER as one of: 'Married', 'Unmarried', 'Divorced', 'Widowed'.",
    "number_of_family_members": "EXTRACT the number of family members as integer.",
    "educational_qualification": "INFER as one of: 'No Formal Education', '10th', '12th', 'Graduate', 'Post Graduate'.",
    "sources_of_income": "EXTRACT all sources of income as an array of strings in English (such as Salary, Business, Agriculture, Pension, Rent).",
    "annual_income": "EXTRACT the annual income in Rupees as integer. Convert phrases like '5 lakh' to 500000.",
    "net_worth": "EXTRACT the net worth in Rupees as integer. Convert phrases like '10 lakh' to 1000000.",
    "religion": "EXTRACT the religion (such as Hindu, Muslim, Christian, Sikh, Jain, Buddhist).",
    "caste_category": "INFER as one of: 'General', 'OBC', 'SC', 'ST'."
}

# Automatically derive context_map dependencies to make the LLM prompts robust
CONTEXT_MAP = {
    "Q_START": [],
    "DOC_AADHAAR_FRONT": [],
    "DOC_AADHAAR_BACK": [],
    "Q_AADHAAR_CONFIRM": ["DOC_AADHAAR_FRONT", "DOC_AADHAAR_BACK"],
    "DOC_PAN": ["Q_AADHAAR_CONFIRM"],
    "Q_PAN_CONFIRM": ["DOC_PAN"],
    "Q_OCCUPATION": ["Q_PAN_CONFIRM"],
    "Q_EMPLOYEE_ID": ["Q_OCCUPATION"],
    "Q_PLACE_OF_POSTING": ["Q_OCCUPATION"],
    "Q_COMPANY_AND_DESIGNATION": ["Q_OCCUPATION"],
    "Q_BUSINESS_DETAILS": ["Q_OCCUPATION"],
    "Q_AADHAAR_AS_ADDRESS_PROOF": ["Q_OCCUPATION"],
    "Q_SELECT_ADDRESS_PROOF_DOC": ["Q_AADHAAR_AS_ADDRESS_PROOF"],
    "Q_INVALID_ADDRESS_PROOF_DOC": ["Q_SELECT_ADDRESS_PROOF_DOC"],
    "DOC_ADDRESS_PROOF_CAPTURE": ["Q_SELECT_ADDRESS_PROOF_DOC"],
    "Q_ADDRESS_PROOF_CONFIRM": ["DOC_ADDRESS_PROOF_CAPTURE"],
    "Q_CORRESPONDENCE_SAME": ["Q_AADHAAR_AS_ADDRESS_PROOF"],
    "Q_SELECT_CORRESPONDENCE_DOC": ["Q_CORRESPONDENCE_SAME"],
    "Q_INVALID_CORRESPONDENCE_DOC": ["Q_SELECT_CORRESPONDENCE_DOC"],
    "DOC_CORRESPONDENCE_CAPTURE": ["Q_SELECT_CORRESPONDENCE_DOC"],
    "Q_CORRESPONDENCE_CONFIRM": ["DOC_CORRESPONDENCE_CAPTURE"],
    "Q_FATHER_NAME": ["Q_CORRESPONDENCE_SAME"],
    "Q_MOBILE": ["Q_FATHER_NAME"],
    "Q_EMAIL": ["Q_MOBILE"],
    "Q_MARITAL": ["Q_EMAIL"],
    "Q_FAMILY_MEMBERS": ["Q_MARITAL"],
    "Q_EDUCATION": ["Q_FAMILY_MEMBERS"],
    "Q_SOURCES_OF_INCOME": ["Q_EDUCATION","Q_OCCUPATION"],
    "Q_ANNUAL_INCOME": ["Q_SOURCES_OF_INCOME"],
    "Q_NET_WORTH": ["Q_ANNUAL_INCOME"],
    "Q_RELIGION": ["Q_NET_WORTH"],
    "Q_CASTE": ["Q_RELIGION"],
    "END": []
}

# The config registry expects scheme_id and interview_graph containing start_node_id and nodes
config_wrapper = {
    "schema_version": "1.0",
    "scheme_id": "sbi-account-opening",
    "description": "SBI Account Opening Form",
    "interview_graph": {
        "start_node_id": "Q_START",
        "nodes": SBI_GRAPH
    },
    "context_map": CONTEXT_MAP,
    "field_instructions": FIELD_INSTRUCTIONS
}

if __name__ == "__main__":
    import json
    
    # 1. Path to shared configs folder
    shared_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'configs'))
    os.makedirs(shared_dir, exist_ok=True)
    shared_file = os.path.join(shared_dir, "sbi-account-opening.yaml")
    
    # 2. Path to config registry configs folder
    registry_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'configs'))
    os.makedirs(registry_dir, exist_ok=True)
    registry_file = os.path.join(registry_dir, "sbi-account-opening.yaml")
    
    # Write to config-registry/configs/sbi-account-opening.yaml
    with open(registry_file, "w", encoding="utf-8") as f:
        yaml.dump(config_wrapper, f, allow_unicode=True, sort_keys=False)
    print(f"Generated {registry_file}")
    
    # Write to services/configs/sbi-account-opening.yaml
    # We maintain name/graph keys for any older parser that might read it
    legacy_wrapper = {
        "schema_version": "1.0",
        "name": "sbi-account-opening",
        "description": "SBI Account Opening Form",
        "graph": SBI_GRAPH,
        "context_map": CONTEXT_MAP,
        "field_instructions": FIELD_INSTRUCTIONS
    }
    with open(shared_file, "w", encoding="utf-8") as f:
        yaml.dump(legacy_wrapper, f, allow_unicode=True, sort_keys=False)
    print(f"Generated {shared_file}")
