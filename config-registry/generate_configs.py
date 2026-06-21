"""
Generate YAML configs for all 11 Mudra business types.

Run this once to create all config files from the mudra_config.py definitions.
Usage: python generate_configs.py
"""

import yaml
import os
import copy

# Base template — all business types share this graph structure
BASE_GRAPH = {
    "DOC_SELFIE": {
        "type": "capture",
        "document_id": "selfie",
        "edges": [{"condition": "always", "next": "DOC_AADHAAR_FRONT"}],
    },
    "DOC_AADHAAR_FRONT": {
        "type": "capture",
        "document_id": "aadhaar_front",
        "edges": [{"condition": "always", "next": "DOC_AADHAAR_BACK"}],
    },
    "DOC_AADHAAR_BACK": {
        "type": "capture",
        "document_id": "aadhaar_back",
        "edges": [{"condition": "always", "next": "START"}],
    },
    "START": {
        "type": "voice-qa",
        "targets": [],
        "edges": [{"condition": "always", "next": "Q_BIZ_TYPE"}],
    },
    "Q_BIZ_TYPE": {
        "type": "voice-qa",
        "text_template": "क्या आप कोई व्यापार करते हैं या किसी कंपनी में नौकरी करते हैं?",
        "targets": ["employment_type"],
        "routing_prompt": "Evaluate if the user is doing business or a job/service. Set 'routing_decision' to 'YES' if they are doing business, 'NO' if they are doing a job/service.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "DOC_UDYAM"},
            {"condition": "routing_decision == 'NO'", "next": "DOC_COMPANY_ID"},
            {"condition": "always", "next": "Q_STATUS"}  # fallback
        ],
    },
    "DOC_UDYAM": {
        "type": "capture",
        "document_id": "udyam",
        "edges": [{"condition": "always", "next": "Q_STATUS"}],
    },
    "DOC_COMPANY_ID": {
        "type": "capture",
        "document_id": "company_id",
        "edges": [{"condition": "always", "next": "Q_STATUS"}],
    },
    "Q_STATUS": {
        "type": "voice-qa",
        "targets": [],
        "edges": [{"condition": "always", "next": "Q_MONTHLY_REV"}],
    },
    "Q_MONTHLY_REV": {
        "targets": ["monthly_revenue"],
        "edges": [{"condition": "always", "next": "Q_MONTHLY_PROFIT"}],
    },
    "Q_MONTHLY_PROFIT": {
        "targets": ["monthly_profit"],
        "edges": [{"condition": "always", "next": "Q_LAST_YEAR_REV"}],
    },
    "Q_LAST_YEAR_REV": {
        "targets": ["last_year_monthly_revenue"],
        "edges": [{"condition": "always", "next": "Q_PERSONS_INVOLVED"}],
    },
    "Q_PERSONS_INVOLVED": {
        "targets": ["persons_involved"],
        "routing_prompt": "Evaluate if the user works alone or with others. Set 'routing_decision' to 'YES' if they work with others, 'NO' if they work alone.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "Q_PAID_EMPLOYEES"},
            # next_fallback is set per config: Q_INVENTORY or Q_HAVE_SHADE
        ],
    },
    "Q_PAID_EMPLOYEES": {
        "targets": ["number_of_paid_employees"],
        "routing_prompt": "Evaluate if any workers are paid employees (outsiders). Set 'routing_decision' to 'YES' if they have paid employees, 'NO' if only family members.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "Q_CURRENT_WAGES"},
            # next_fallback set per config
        ],
    },
    "Q_CURRENT_WAGES": {
        "targets": ["current_wages"],
        "edges": [],  # next set per config
    },
    "Q_INVENTORY": {
        "targets": ["inventory_amount"],
        "edges": [{"condition": "always", "next": "Q_DEBTORS"}],
    },
    "Q_DEBTORS": {
        "targets": ["debtors_amount"],
        "edges": [{"condition": "always", "next": "Q_CREDITORS"}],
    },
    "Q_CREDITORS": {
        "targets": ["creditors_amount"],
        "edges": [{"condition": "always", "next": "Q_PROPOSED_REV"}],
    },
    "Q_PROPOSED_REV": {
        "targets": ["proposed_monthly_revenue"],
        "edges": [{"condition": "always", "next": "Q_PROPOSED_HIRING"}],
    },
    "Q_PROPOSED_HIRING": {
        "targets": ["proposed_number_of_people"],
        "routing_prompt": "Evaluate if the user will hire new people after the loan. Set 'routing_decision' to 'YES' if they will hire new people, 'NO' if not.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "Q_PROPOSED_WAGES"},
            {"condition": "always", "next": "Q_NEED_MACHINES"},
        ],
    },
    "Q_PROPOSED_WAGES": {
        "targets": ["proposed_wages"],
        "edges": [{"condition": "always", "next": "Q_NEED_MACHINES"}],
    },
    "Q_NEED_MACHINES": {
        "targets": ["needs_machine", "machine_name"],
        "routing_prompt": "Evaluate if the user needs to purchase any new machine or equipment. Set 'routing_decision' to 'YES' if they need a machine/equipment, 'NO' if not.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "Q_MACHINE_DETAILS"},
            {"condition": "always", "next": "Q_PRIOR_LOAN"},
        ],
    },
    "Q_MACHINE_DETAILS": {
        "text_template": "यह मशीन किस काम आएगी, कहाँ से लेंगे और इसकी कीमत क्या होगी?",
        "targets": ["machine_purpose", "machine_supplier", "machine_cost"],
        "edges": [{"condition": "always", "next": "Q_PRIOR_LOAN"}],
    },
    "Q_PRIOR_LOAN": {
        "text_template": "क्या आपने पहले कभी कर्ज लिया है? कभी किस्त भरने में दिक्कत तो नहीं हुई? मतलब लोन लिया हो और किश्त ना दी हो या देर से दी हो?",
        "targets": ["previous_loan_detail", "previous_loan_default_flag", "default_reason"],
        "routing_prompt": "Evaluate if the user has taken any loan before. Set 'routing_decision' to 'YES' if they have a previous loan, 'NO' if not.",
        "edges": [
            {"condition": "routing_decision == 'YES'", "next": "Q_CURRENT_EMI"},
            {"condition": "always", "next": "Q_FAMILY"},
        ],
    },
    "Q_CURRENT_EMI": {
        "text_template": "अभी कोई और कर्ज या किस्त चल रही है क्या?",
        "targets": ["current_emi_value", "current_emi_lender", "current_emi_outstanding"],
        "edges": [{"condition": "always", "next": "Q_FAMILY"}],
    },
    "Q_FAMILY": {
        "text_template": "{name} जी, घर में आपके साथ कौन-कौन रहता है?",
        "targets": ["number_of_family_members", "marital_status", "number_of_kids"],
        "edges": [{"condition": "always", "next": "Q_EDUCATION"}],
    },
    "Q_EDUCATION": {
        "text_template": "आपने कहाँ तक पढ़ाई की है? काम का हिसाब खुद कर लेते हैं, या किसी और से कराते हैं?",
        "targets": ["education_level"],
        "edges": [{"condition": "always", "next": "Q_COBORROWER"}],
    },
    "Q_COBORROWER": {
        "type": "voice-qa",
        "text_template": "यह काम आप खुद चलाते हैं, या घर का कोई और भी देखता है?",
        "targets": ["co_borrower"],
        "edges": [{"condition": "always", "next": "DOC_PAN"}],
    },
    "DOC_PAN": {
        "type": "capture",
        "document_id": "pan",
        "edges": [{"condition": "always", "next": "DOC_BANK_STATEMENT"}],
    },
    "DOC_BANK_STATEMENT": {
        "type": "capture",
        "document_id": "bank_statement",
        "edges": [],
    },
}

# ─── Business-specific configurations ───
BUSINESSES = {
    "mudra-clothing": {
        "display_name": "Mudra Loan - Clothing",
        "welcome": "कपड़े की दुकान",
        "status": "आपकी कपड़ों की दुकान कैसी चल रही है?",
        "sale_word": "बिक्री",
        "profit_text": "दुकान का सारा खर्चा निकालने के बाद",
        "inventory": "अभी दुकान में जो कपड़े रखे हुए हैं, उनकी कुल क़ीमत कितनी होगी?",
        "machines": "क्या कोई कपड़ा काटने की मशीन, सिलाई मशीन, अलमारी, काउंटर या लाइट वगैरह भी लेना है?",
        "is_livestock": False,
        "is_service": False,
    },
    "mudra-poultry": {
        "display_name": "Mudra Loan - Poultry",
        "welcome": "मुर्गी पालन",
        "status": "आपका मुर्गी पालन का काम कैसा चल रहा है?",
        "sale_word": "बिक्री",
        "profit_text": "दाना, बिजली, मज़दूरी और बाकी सब खर्चा निकालने के बाद",
        "inventory": "अभी आपके पोल्ट्री फार्म में जो मुर्गियाँ, दाना और दवाइयाँ हैं, आगर आज के भाव से देखा जाए तो लगभग कितने रूपये की होगी?",
        "machines": "क्या कोई मशीन, दाना रखने की टंकी, पानी की टंकी, हीटर या और सामान भी लेना है?",
        "is_livestock": True,
        "is_service": False,
    },
    "mudra-goatry": {
        "display_name": "Mudra Loan - Goatry",
        "welcome": "बकरी पालन",
        "status": "आपका बकरी पालन का काम कैसा चल रहा है?",
        "sale_word": "बिक्री",
        "profit_text": "दाना, बिजली, मज़दूरी और बाकी सब खर्चा निकालने के बाद",
        "inventory": "अभी आपके पास जो बकरियाँ, चारा और दवाइयाँ हैं, आगर आज के भाव से देखा जाए तो लगभग कितने रूपये की होगी?",
        "machines": "क्या कोई मशीन, दाना रखने की टंकी, पानी की टंकी, हीटर या और सामान भी लेना है?",
        "is_livestock": True,
        "is_service": False,
    },
    "mudra-dairy": {
        "display_name": "Mudra Loan - Dairy",
        "welcome": "डेयरी",
        "status": "आपका डेयरी का काम कैसा चल रहा है?",
        "sale_word": "बिक्री",
        "profit_text": "दाना, बिजली, मज़दूरी और बाकी सब खर्चा निकालने के बाद",
        "inventory": "अभी आपके पास जो गाय-भैंस, चारा और दवाइयाँ हैं, आगर आज के भाव से देखा जाए तो लगभग कितने रूपये की होगी?",
        "machines": "क्या कोई दूध निकालनी मशीन, कूलर, टंकी, या और सामान भी लेना है?",
        "is_livestock": True,
        "is_service": False,
    },
    "mudra-electric": {
        "display_name": "Mudra Loan - Electrical",
        "welcome": "बिजली सामान मरम्मत",
        "status": "अभी दुकान कैसी चल रही है?",
        "sale_word": "बिक्री",
        "profit_text": "दुकान का सारा खर्चा निकालने के बाद",
        "inventory": "अभी दुकान में जो मशीनें, ओज़ार और सामान है, उनकी कुल क़ीमत होगी? मतलब अभी दुकान लगभग कितने रुपये का सामान है?",
        "machines": "क्या कोई नई मशीन, मोटर, ओज़ार या और सामान भी लेना है?",
        "is_livestock": False,
        "is_service": False,
    },
    "mudra-tailor": {
        "display_name": "Mudra Loan - Tailor",
        "welcome": "सिलाई की दुकान",
        "status": "अभी सिलाई का काम कैसा चल रहा है?",
        "sale_word": "बिक्री",
        "profit_text": "दुकान का सारा खर्चा निकालने के बाद",
        "inventory": "अभी दुकान में जो कपड़ा, मशीनें और सामान है, उनकी कुल क़ीमत होगी?",
        "machines": "क्या कोई नई सिलाई मशीन, मोटर, ओज़ार या और सामान भी लेना है?",
        "is_livestock": False,
        "is_service": False,
    },
    "mudra-csc": {
        "display_name": "Mudra Loan - CSC Center",
        "welcome": "सीएससी सेंटर",
        "status": "अभी सेंटर कैसा चल रहा है?",
        "sale_word": "कमाई",
        "profit_text": "किराया, बिजली, सामान और बाकी खर्च निकालने के बाद",
        "inventory": "अभी सेंटर में जो कंप्यूटर, प्रिंटर, और मशीनें हैं, उनकी कुल कीमत कितनी होगी?",
        "machines": "क्या कोई नया कंप्यूटर, प्रिंटर, या मशीन लेनी है?",
        "is_livestock": False,
        "is_service": True,
    },
    "mudra-salon": {
        "display_name": "Mudra Loan - Salon",
        "welcome": "सैलून",
        "status": "अभी सैलून कैसा चल रहा है?",
        "sale_word": "कमाई",
        "profit_text": "किराया, बिजली, सामान और बाकी खर्च निकालने के बाद",
        "inventory": "दुकान में अभी जो कुर्सियाँ, ब्यूटी उपकरण और प्रोडक्ट्स हैं, उनकी कुल कीमत लगभग कितनी होगी?",
        "machines": "क्या कोई नई मशीन, चेयर, या उपकरण लेने का प्लान है?",
        "is_livestock": False,
        "is_service": True,
    },
    "mudra-garage": {
        "display_name": "Mudra Loan - Garage",
        "welcome": "कार मैकेनिक",
        "status": "अभी गैराज का काम कैसा चल रहा है?",
        "sale_word": "कमाई",
        "profit_text": "किराया, बिजली, सामान और बाकी खर्च निकालने के बाद",
        "inventory": "गैराज में अभी जो मशीनें, टूल्स और स्पेयर पार्ट्स हैं, उनकी कुल कीमत लगभग कितनी होगी?",
        "machines": "क्या कोई नई मशीन, कार लिफ्ट, डायग्नोस्टिक मशीन या टूल्स लेने का प्लान है?",
        "is_livestock": False,
        "is_service": True,
    },
    "mudra-furniture": {
        "display_name": "Mudra Loan - Furniture",
        "welcome": "फर्नीचर",
        "status": "अभी फर्नीचर का काम कैसा चल रहा है?",
        "sale_word": "कमाई",
        "profit_text": "किराया, बिजली, सामान और बाकी खर्च निकालने के बाद",
        "inventory": "दुकान में अभी जो लकड़ी, मशीनें, और टूल्स हैं, उनकी कुल कीमत लगभग कितनी होगी?",
        "machines": "क्या कोई नई कटिंग मशीन, ड्रिल मशीन, या औज़ार खरीदने का प्लान है?",
        "is_livestock": False,
        "is_service": True,
    },
}


def build_config(scheme_id: str, biz: dict) -> dict:
    """Build a full scheme config dict from business definition."""
    is_livestock = biz["is_livestock"]
    sale_word = biz["sale_word"]
    profit_text = biz["profit_text"]

    # Determine fallback node for branching
    inventory_fallback = "Q_HAVE_SHADE" if is_livestock else "Q_INVENTORY"

    # Deep copy base graph and fill in text templates
    nodes = {}
    for node_id, base in BASE_GRAPH.items():
        node = copy.deepcopy(base)

        # Default to voice-qa if not specified
        if "type" not in node:
            node["type"] = "voice-qa"

        # Set text templates per business type
        if node_id == "START":
            node["text_template"] = (
                f"{{name}} जी, स्मार्ट मुद्रा समाधान में आपका स्वागत है। "
                f"मैं, आपके {biz['welcome']} के काम में आपको आगे बढ़ाने के लिए जो लोन चाहिए, "
                f"उसके बारे में बात कर रही हूँ। आपको जो कर्ज चाहिए, उसे जल्दी दिलाने के लिए "
                f"मुझे आपसे थोड़ी जानकारी लेनी है। जैसे यह कर्ज किस काम में लगेगा, पैसा कहाँ "
                f"खर्च होगा, और उससे {sale_word} कितनी बढ़ेगी। क्या आप बताने के लिए तैयार हैं?"
            )
        elif node_id == "Q_STATUS":
            node["text_template"] = biz["status"]
        elif node_id == "Q_MONTHLY_REV":
            node["text_template"] = f"अभी आप महीने में लगभग कितनी {sale_word} कर लेते हैं?"
        elif node_id == "Q_MONTHLY_PROFIT":
            node["text_template"] = f"{profit_text}, महीने में कितना पैसा बच जाता है?"
        elif node_id == "Q_LAST_YEAR_REV":
            node["text_template"] = f"अच्छा! पहले, जब काम नया था, तब महीने की {sale_word} कितनी होती थी? पिछले एक साल में काम कुछ बढ़ा है क्या?"
        elif node_id == "Q_PERSONS_INVOLVED":
            node["text_template"] = "अभी काम पर आपके अलावा और कौन-कौन काम करता है?"
            node["edges"].append({"condition": "always", "next": inventory_fallback})
        elif node_id == "Q_PAID_EMPLOYEES":
            node["text_template"] = "उनमें से घर के लोग हैं या बाहर के लोग भी हैं, जिन्हें पगार देनी पड़ती है?"
            node["edges"].append({"condition": "always", "next": inventory_fallback})
        elif node_id == "Q_CURRENT_WAGES":
            node["text_template"] = "उन लोगों को पगार देने में महीने का कितना खर्च हो जाता है?"
            node["edges"] = [{"condition": "always", "next": inventory_fallback}]
        elif node_id == "Q_INVENTORY":
            node["text_template"] = biz["inventory"]
        elif node_id == "Q_DEBTORS":
            node["text_template"] = "क्या कोई उधार का पैसा है, जो आपको लोगों से मिलना बाकी है?"
        elif node_id == "Q_CREDITORS":
            node["text_template"] = "और क्या कोई पैसा ऐसा है, जो आपको देना बाकी है? जैसे आपने माल लिया है और पैसा अभी नहीं दिया?"
        elif node_id == "Q_PROPOSED_REV":
            node["text_template"] = f"बहुत अच्छा! अब यह जो कर्ज आप लेने वाले हैं, कर्ज मिलने के बाद महीने की {sale_word} कितनी हो जाएगी, ऐसा आपको क्या लगता है?"
        elif node_id == "Q_PROPOSED_HIRING":
            node["text_template"] = "कर्ज मिलने के बाद, क्या काम के लिए और आदमी रखने पड़ेंगे, या अभी जैसे चल रहा है वैसे चल जाएगा?"
        elif node_id == "Q_PROPOSED_WAGES":
            node["text_template"] = "उन नए लोगों को पगार देने में महीने का कितना खर्च होगा?"
        elif node_id == "Q_NEED_MACHINES":
            node["text_template"] = biz["machines"]

        nodes[node_id] = node

    # Add livestock-specific nodes
    if is_livestock:
        nodes["Q_HAVE_SHADE"] = {
            "text_template": "क्या आपने जानवरों के लिए अलग से शेड बनाया हुआ है?",
            "targets": ["has_shade"],
            "routing_prompt": "Evaluate if the user has a shade/shelter for animals. Set 'routing_decision' to 'YES' if they have a shade, 'NO' if not.",
            "edges": [
                {"condition": "routing_decision == 'YES'", "next": "Q_SHADE_DETAILS"},
                {"condition": "always", "next": "Q_INVENTORY"},
            ],
        }
        nodes["Q_SHADE_DETAILS"] = {
            "text_template": "यह शेड कहाँ है, और यह खुद की जगह पर है या किराए की?",
            "targets": ["shade_location", "shade_owned_or_rented"],
            "edges": [{"condition": "always", "next": "Q_INVENTORY"}],
        }

    # Read field instructions from grocery (shared across all)
    grocery_path = os.path.join(os.path.dirname(__file__), "configs", "mudra-grocery.yaml")
    with open(grocery_path, "r", encoding="utf-8") as f:
        grocery = yaml.safe_load(f)

    field_instructions = grocery.get("field_instructions", {})

    # Add shade-specific fields for livestock
    if is_livestock:
        field_instructions["has_shade"] = "INFER as 'Yes' or 'No'. Whether the user has built a separate shade/shelter for animals."
        field_instructions["shade_location"] = "INFER the location in ENGLISH. Example: 'In the village', 'Near the farm'."
        field_instructions["shade_owned_or_rented"] = "INFER as 'Owned' or 'Rented' ONLY."

    config = {
        "scheme_id": scheme_id,
        "display_name": biz["display_name"],
        "languages": ["hi", "en"],
        "tts": grocery.get("tts", {}),
        "stt": grocery.get("stt", {}),
        "interview_graph": {
            "start_node_id": "DOC_SELFIE",
            "nodes": nodes,
        },
        "context_map": grocery.get("context_map", {}),
        "field_instructions": field_instructions,
        "financial_rules": grocery.get("financial_rules", {}),
        "documents_required": grocery.get("documents_required", []),
        "db_mapping": grocery.get("db_mapping", {}),
    }

    # Add shade nodes to context map for livestock
    if is_livestock:
        config["context_map"]["Q_HAVE_SHADE"] = []
        config["context_map"]["Q_SHADE_DETAILS"] = ["Q_HAVE_SHADE"]

    return config


def main():
    """Generate all business type YAML config files."""
    output_dir = os.path.join(os.path.dirname(__file__), "configs")
    os.makedirs(output_dir, exist_ok=True)

    for scheme_id, biz in BUSINESSES.items():
        config = build_config(scheme_id, biz)
        filepath = os.path.join(output_dir, f"{scheme_id}.yaml")

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, width=200)

        node_count = len(config["interview_graph"]["nodes"])
        print(f"✅ Generated {scheme_id}.yaml ({node_count} nodes)")

    print(f"\n✅ Generated {len(BUSINESSES)} config files in {output_dir}")


if __name__ == "__main__":
    main()
