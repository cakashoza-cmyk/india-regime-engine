"""Seed for the industry and city catalogue (Lending Radar v3). Run: python -m engine.catalog_seed -> engine/industries.json, engine/cities.json.
Industries that are not scored directly use their nearest parent scored sector: 'proxy: parent sector'."""
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent
# id | name | group | parent scored sector | NIC | focus (analytical framing, not data)
PROXY = """
dairy_products|Dairy products (milk, ghee, cheese)|Agri-processing|marine_meat_dairy|105|milk procurement price vs realisation; cooperative competition
seafood_processing|Seafood / shrimp processing & export|Agri-processing|marine_meat_dairy|102|US shrimp duties; antibiotic rejections; farm-gate prices
meat_poultry_processing|Meat & poultry processing|Agri-processing|marine_meat_dairy|101|feed (maize/soya) cost; export licences
bakery_confectionery|Bakery, biscuits & confectionery|Agri-processing|food_processing|107|wheat/sugar/palm-oil cost; distributor credit
flour_dal_mills|Flour, dal & grain mills|Agri-processing|food_processing|106|wheat/pulse prices; stock limits
snacks_namkeen|Snacks & namkeen|Agri-processing|food_processing|107|edible-oil cost; branded competition
animal_feed|Animal & poultry feed|Agri-processing|food_processing|108|maize and soymeal prices; poultry farm payments
distilleries_ethanol|Distilleries & ethanol|Manufacturing|beverages|110|ethanol procurement price; grain/molasses cost; state excise
soft_drinks_water|Soft drinks & packaged water|Manufacturing|beverages|110|seasonal demand; PET and sugar cost
bidi_making|Bidi making|Manufacturing|tobacco|120|leaf cost; cess changes; home-worker wages
cotton_ginning|Cotton ginning & pressing|Manufacturing|cotton_textiles|131|kapas prices; CCI procurement; mill payments
handloom_powerloom|Handloom & powerloom weaving|Manufacturing|cotton_textiles|131|yarn prices; trader payment cycles; power tariff
silk_weaving|Silk weaving & sarees|Manufacturing|cotton_textiles|131|raw silk prices; wedding-season demand; trader credit
woollen_textiles|Woollen & shawl textiles|Manufacturing|cotton_textiles|131|imported wool prices; winter demand
textile_processing|Textile dyeing & processing houses|Manufacturing|mmf_textiles|131|coal/gas cost; effluent norms; job-work rates
technical_textiles|Technical textiles & nonwovens|Manufacturing|mmf_textiles|139|polymer prices; institutional orders
home_textiles|Home textiles & made-ups (towels, bedsheets)|Manufacturing|cotton_textiles|139|US retailer orders; cotton yarn prices
hosiery_knitwear|Hosiery & knitwear|Manufacturing|apparel|143|yarn prices; winter-season orders; dealer credit
footwear|Footwear|Manufacturing|leather|152|EU/US orders; rubber/PU cost; BIS quality rules
leather_tanning|Leather tanning|Manufacturing|leather|151|hide prices; effluent rules; export orders
leather_goods|Leather goods (bags, belts, gloves)|Manufacturing|leather|151|EU orders; finished-leather prices
plywood_laminates|Plywood, veneer & laminates|Manufacturing|wood_plywood|162|timber/face-veneer prices; real-estate demand
sawmills_timber|Sawmills & timber|Manufacturing|wood_plywood|161|log imports; construction demand
packaging_corrugated|Corrugated boxes & paper packaging|Manufacturing|paper|170|kraft paper prices; FMCG/e-commerce volumes
printing_publishing|Printing & publishing|Manufacturing|paper|181|paper prices; label and packaging demand (NIC 18 not in IIP: proxy)
lubricants|Lubricants & petroleum products|Manufacturing|refining|192|base-oil prices; auto aftermarket demand
agrochemicals|Agrochemicals & pesticides|Manufacturing|chemicals_dyes|202|monsoon; dealer credit; China technical prices
paints_coatings|Paints & coatings|Manufacturing|chemicals_dyes|202|crude-linked raw materials; housing demand
soaps_cosmetics|Soaps, detergents & cosmetics|Manufacturing|chemicals_dyes|202|palm-oil and LAB prices; distributor credit
specialty_chemicals|Specialty & fine chemicals|Manufacturing|chemicals_dyes|201|China prices; export orders; pollution closure orders
industrial_gases|Industrial gases|Manufacturing|chemicals_dyes|201|power cost; steel/health demand
fireworks_matches|Fireworks & safety matches|Manufacturing|chemicals_dyes|202|Diwali demand; Supreme Court/PESO restrictions; accidents
manmade_fibres|Man-made fibres & yarn (polyester, viscose)|Manufacturing|petrochem|203|PTA/MEG prices; China imports
api_bulk_drugs|API / bulk drugs|Manufacturing|pharma|210|China KSM prices; USFDA status; PLI
formulations|Pharma formulations|Manufacturing|pharma|210|USFDA observations; US generic price erosion; NLEM caps
ayush_herbal|Ayurvedic & herbal products|Manufacturing|pharma|210|herb prices; distributor credit
medical_devices|Medical devices & consumables|Manufacturing|pharma|325|import competition; hospital payments (NIC 325: proxy)
rubber_tyres|Tyres & rubber products|Manufacturing|plastics|221|natural rubber price; OEM volumes
plastic_packaging|Plastic packaging & films|Manufacturing|plastics|222|polymer prices; single-use plastic bans
pvc_pipes|PVC pipes & fittings|Manufacturing|plastics|222|PVC resin price; housing and irrigation demand
bricks_kilns|Brick kilns|Manufacturing|cement|239|coal price; construction demand; kiln closure orders
stone_granite|Stone, granite & marble processing|Manufacturing|cement|239|export demand; mining leases; real-estate demand
refractories|Refractories|Manufacturing|ceramics|239|steel-sector demand; raw-material imports
steel_rerolling|Steel re-rolling & TMT|Manufacturing|metals|241|billet/scrap prices; construction demand
sponge_iron|Sponge iron & ferro alloys|Manufacturing|metals|241|iron ore and coal prices; power cost
aluminium_products|Aluminium & aluminium products|Manufacturing|metals|242|LME aluminium; power cost
castings_forgings|Castings & forgings|Manufacturing|metals|243|pig iron/scrap prices; auto and tractor orders
fasteners_hardware|Fasteners & hardware|Manufacturing|nonferrous_brass|259|steel wire-rod prices; export orders
steel_utensils|Steel & metal utensils|Manufacturing|nonferrous_brass|259|stainless steel prices; dealer credit
hand_tools|Hand tools & cutting tools|Manufacturing|nonferrous_brass|259|steel prices; export orders
electronic_components|Electronic components & PCBs|Manufacturing|electronics|261|China imports; PLI; OEM payments
mobile_assembly|Mobile & consumer-electronics assembly|Manufacturing|electronics|264|brand orders; component imports; PLI
solar_modules|Solar cells & modules|Manufacturing|electronics|261|China cell prices; ALMM rules; developer orders
cables_wires|Cables & wires|Manufacturing|electrical_eq|273|copper/aluminium prices; utility and builder orders
transformers_switchgear|Transformers & switchgear|Manufacturing|electrical_eq|271|CRGO/copper prices; utility payment delays
lighting_led|Lighting & LED products|Manufacturing|electrical_eq|274|China imports; dealer credit
appliances_fans|Home appliances & fans|Manufacturing|electrical_eq|275|seasonal demand; copper/steel cost; BEE norms
batteries|Batteries|Manufacturing|electrical_eq|272|lead/lithium prices; auto aftermarket
pumps_valves|Pumps, motors & valves|Manufacturing|engineering|281|irrigation demand; copper cost; export orders
machine_tools|Machine tools|Manufacturing|engineering|282|capex cycle; auto orders
textile_machinery|Textile machinery|Manufacturing|engineering|282|textile capex; imported machine competition
tractors_agri_machinery|Tractors & farm machinery|Manufacturing|engineering|282|monsoon; farm incomes; dealer stocks
diesel_engines|Diesel engines & gensets|Manufacturing|engineering|281|emission norms; infra demand
vehicle_oem|Cars & commercial vehicles (OEM)|Manufacturing|auto_components|291|dealer inventory; freight demand; EV shift
ev_components|EV & EV components|Manufacturing|auto_components|293|subsidy rules; battery prices; OEM payments
two_wheelers|Two-wheelers|Manufacturing|other_transport|309|rural demand; dealer inventory
bicycles|Bicycles & parts|Manufacturing|other_transport|309|steel prices; government tenders; China imports
shipbuilding|Shipbuilding & repair|Manufacturing|other_transport|301|order book; government contracts
railway_wagons|Railway wagons & coaches|Manufacturing|other_transport|302|Indian Railways orders; steel prices
defence_aerospace|Defence & aerospace parts|Manufacturing|other_transport|303|defence orders; long receivables
wooden_furniture|Wooden & modular furniture|Manufacturing|furniture_misc|310|timber prices; housing demand; export orders
gold_jewellery|Gold jewellery manufacturing|Manufacturing|diamonds|321|gold prices; hallmarking; wedding demand
imitation_jewellery|Imitation jewellery|Manufacturing|diamonds|321|brass/alloy prices; festival demand
sports_goods|Sports goods|Manufacturing|handicrafts|323|export orders; leather/willow supply
toys|Toys|Manufacturing|handicrafts|324|BIS quality rules; China imports
coir_products|Coir products|Manufacturing|jute_coir|139|husk supply; export orders
jute_mills|Jute mills & products|Manufacturing|jute_coir|139|raw jute price; government sacking orders
dairy_farming|Dairy farming|Agriculture & Allied|agriculture|014|milk price; fodder cost; cattle disease
poultry_farming|Poultry farming|Agriculture & Allied|agriculture|014|maize/soya feed cost; bird flu
fisheries_aquaculture|Fisheries & aquaculture|Agriculture & Allied|agriculture|032|shrimp prices; disease; export duties
horticulture|Horticulture & floriculture|Agriculture & Allied|agriculture|011|crop prices; weather; cold storage
plantation_rubber|Rubber & other plantations|Agriculture & Allied|agriculture|012|natural rubber price; labour cost
seeds|Seeds|Agriculture & Allied|agriculture|016|monsoon; dealer returns
sericulture|Sericulture|Agriculture & Allied|agriculture|014|cocoon prices; silk demand
cold_storage|Cold storage & warehousing for agri|Agriculture & Allied|transport_ops|521|potato/fruit stock levels; power cost
coal_mining|Coal mining & washeries|Infrastructure & Core|mining|051|coal prices; offtake by power plants
quarrying_sand|Stone quarrying, sand & aggregates|Infrastructure & Core|mining|081|mining bans; construction demand
iron_ore_mining|Iron ore mining|Infrastructure & Core|mining|071|ore prices; export duty; lease renewals
residential_real_estate|Residential real estate developers|Infrastructure & Core|commercial_real_estate|410|unsold inventory; RERA escrow; sales velocity
solar_epc|Solar EPC & rooftop|Infrastructure & Core|renewables|432|module prices; DISCOM payments
water_sanitation|Water & sanitation projects|Infrastructure & Core|other_infra|360|government payment delays (Jal Jeevan)
oil_gas_pipelines|Oil & gas pipelines / city gas|Infrastructure & Core|other_infra|352|gas prices; connections; PNGRB tariffs
civil_contractors|Civil & government contractors|Infrastructure & Core|construction|421|government bill payments; cement/steel cost
logistics_warehousing|Logistics & warehousing|Services|transport_ops|521|freight volumes; e-commerce demand; rentals
trucking_fleet|Truck fleet operators|Services|transport_ops|492|diesel price; freight rates; EMI burden
restaurants_cafes|Restaurants & cafes|Services|tourism_hotels|561|footfall; food inflation; rentals
it_bpo|IT-enabled services & BPO|Services|software_it|822|client billing rates; attrition
hospitals_healthcare|Hospitals & diagnostics|Services|other_services|861|insurer/government (PMJAY) payments; occupancy
education_institutions|Schools, colleges & coaching|Services|other_services|853|enrolments; fee regulation
media_entertainment|Media, cinema & entertainment|Services|other_services|591|ad revenue; footfall
microfinance|Microfinance institutions (bank exposure)|Services|nbfc|649|borrower over-indebtedness; collection efficiency
textile_trading|Textile trading|Trade|wholesale_trade|464|trader payment cycles; GST invoice mismatch
diamond_trading|Diamond & jewellery trading|Trade|wholesale_trade|464|polished price; credit to buyers abroad
agri_commodity_trading|Agri commodity & mandi trading|Trade|wholesale_trade|462|price swings; stock limits
steel_trading|Steel & metal trading|Trade|wholesale_trade|466|steel price swings; builder credit
pharma_distribution|Pharma distribution|Trade|wholesale_trade|464|retailer credit; trade margins
fmcg_distribution|FMCG distribution|Trade|wholesale_trade|463|quick-commerce disruption; brand credit terms
auto_dealerships|Auto dealerships|Trade|retail_trade|451|inventory days; OEM push; trade-advance
jewellery_retail|Jewellery retail|Trade|retail_trade|477|gold prices; gold metal loan; inventory
electronics_retail|Electronics & mobile retail|Trade|retail_trade|474|online competition; brand schemes
ecommerce_sellers|E-commerce sellers|Trade|retail_trade|479|marketplace fees; returns; settlement cycles
fuel_stations|Fuel stations|Trade|retail_trade|473|OMC margins; EV shift
job_work_units|Job-work units (engineering/textiles)|MSME|msme_micro_small|25|principal's payment cycle; order concentration
fabrication_workshops|Fabrication & machining workshops|MSME|msme_micro_small|25|steel prices; order book from large firms
tailoring_units|Small tailoring & garment units|MSME|msme_micro_small|14|trader orders; seasonal demand
small_food_units|Small food & bakery units (MSME)|MSME|msme_micro_small|10|FSSAI compliance; local competition
"""
CITIES = """
JK|Srinagar|handicrafts,woollen_textiles,horticulture,tourism_hotels
JK|Jammu|tourism_hotels,pharma,steel_rerolling
JK|Kathua|pharma,steel_rerolling
JK|Samba|pharma,plastics
HP|Baddi|pharma,formulations,fmcg_distribution
HP|Nalagarh|pharma,electrical_eq
HP|Shimla|horticulture,tourism_hotels
HP|Kala Amb|steel_rerolling,paper
HP|Parwanoo|engineering,fruits_veg
PB|Ludhiana|hosiery_knitwear,bicycles,fasteners_hardware,steel_rerolling
PB|Jalandhar|sports_goods,hand_tools,leather
PB|Amritsar|rice_milling,woollen_textiles,tourism_hotels
PB|Mandi Gobindgarh|steel_rerolling,castings_forgings
PB|Batala|castings_forgings,machine_tools
PB|Mohali|it_bpo,tractors_agri_machinery,pharma
PB|Bathinda|refining,cotton_ginning
CH|Chandigarh|it_bpo,hospitals_healthcare,retail_trade
UK|Haridwar|pharma,fmcg_distribution,vehicle_oem
UK|Rudrapur|auto_components,two_wheelers,pharma
UK|Dehradun|education_institutions,tourism_hotels,pharma
UK|Kashipur|paper,sugar
HR|Panipat|home_textiles,carpets,refining,woollen_textiles
HR|Gurugram|vehicle_oem,auto_components,software_it,commercial_real_estate
HR|Manesar|vehicle_oem,two_wheelers,auto_components
HR|Faridabad|auto_components,engineering,tractors_agri_machinery
HR|Sonipat|plastics,footwear
HR|Karnal|rice_milling,dairy_products
HR|Yamunanagar|plywood_laminates,steel_utensils,sugar
HR|Bahadurgarh|footwear,plastics
HR|Hisar|steel_utensils,cotton_ginning
DL|Delhi|wholesale_trade,textile_trading,electronics_retail,hospitals_healthcare,professional_services
DL|Okhla|apparel,printing_publishing
DL|Narela-Bawana|plastics,footwear,fabrication_workshops
RJ|Jaipur|gold_jewellery,diamonds,handicrafts,carpets,tourism_hotels
RJ|Jodhpur|wooden_furniture,handicrafts,stone_granite
RJ|Bhilwara|manmade_fibres,textile_processing,mmf_textiles
RJ|Kishangarh|stone_granite
RJ|Udaipur|stone_granite,mining,tourism_hotels
RJ|Kota|education_institutions,stone_granite,chemicals_dyes
RJ|Bhiwadi|auto_components,engineering
RJ|Neemrana|auto_components,electrical_eq
RJ|Alwar|edible_oil,engineering
RJ|Pali|textile_processing
RJ|Balotra|textile_processing
RJ|Jaisalmer|renewables,solar_epc
RJ|Bikaner|snacks_namkeen,woollen_textiles,coal_mining
UP|Kanpur|leather_tanning,leather_goods,footwear,flour_dal_mills
UP|Agra|footwear,tourism_hotels,stone_granite
UP|Noida|mobile_assembly,electronic_components,software_it,apparel
UP|Ghaziabad|engineering,steel_rerolling,fabrication_workshops
UP|Moradabad|nonferrous_brass,handicrafts,steel_utensils
UP|Firozabad|glass,imitation_jewellery
UP|Bhadohi|carpets
UP|Mirzapur|carpets,cement
UP|Varanasi|silk_weaving,tourism_hotels
UP|Aligarh|hand_tools,fasteners_hardware
UP|Meerut|sports_goods,sugar
UP|Muzaffarnagar|sugar,paper,steel_rerolling
UP|Lucknow|hospitals_healthcare,handicrafts,residential_real_estate
UP|Gorakhpur|distilleries_ethanol,cement
UP|Saharanpur|wooden_furniture,sugar
UP|Unnao|meat_poultry_processing,leather_tanning
UP|Khurja|ceramics
BR|Patna|wholesale_trade,residential_real_estate
BR|Muzaffarpur|fruits_veg,food_processing
BR|Bhagalpur|silk_weaving
BR|Begusarai|refining,fertiliser
SK|Gangtok|tourism_hotels,pharma
AR|Itanagar|tourism_hotels,horticulture
NL|Dimapur|wholesale_trade,horticulture
MN|Imphal|handicrafts,horticulture
MZ|Aizawl|horticulture,handicrafts
TR|Agartala|plantation_rubber,tea
ML|Byrnihat|cement,steel_rerolling
ML|Shillong|tourism_hotels,horticulture
AS|Guwahati|wholesale_trade,residential_real_estate,logistics_warehousing
AS|Dibrugarh|tea,refining
AS|Jorhat|tea
AS|Tinsukia|tea,plywood_laminates
AS|Numaligarh|refining
WB|Kolkata|jute_mills,wholesale_trade,gold_jewellery,leather_goods
WB|Howrah|castings_forgings,engineering,jute_mills
WB|Durgapur|metals,sponge_iron
WB|Asansol|coal_mining,steel_rerolling
WB|Haldia|petrochem,ports,chemicals_dyes
WB|Siliguri|tea,logistics_warehousing
WB|Burdwan|rice_milling
JH|Jamshedpur|metals,auto_components,vehicle_oem
JH|Dhanbad|coal_mining
JH|Bokaro|metals
JH|Ranchi|engineering,mining
OD|Bhubaneswar|it_bpo,metals,residential_real_estate
OD|Angul|aluminium_products,metals,coal_mining
OD|Jharsuguda|aluminium_products,sponge_iron
OD|Rourkela|metals,sponge_iron
OD|Paradip|ports,fertiliser,refining
OD|Kalinganagar|metals
CG|Raipur|steel_rerolling,sponge_iron,rice_milling
CG|Bhilai|metals
CG|Korba|power,coal_mining,aluminium_products
CG|Raigarh|sponge_iron,power
MP|Indore|pharma,soya_proxy,automotive_proxy,snacks_namkeen
MP|Pithampur|vehicle_oem,auto_components,pharma
MP|Bhopal|engineering,electrical_eq
MP|Jabalpur|defence_aerospace,stone_granite
MP|Gwalior|engineering,stone_granite
MP|Dewas|pharma,engineering
MP|Mandideep|engineering,pharma
GJ|Surat|mmf_textiles,diamonds,textile_trading,textile_processing,manmade_fibres
GJ|Ahmedabad|pharma,cotton_textiles,chemicals_dyes,engineering
GJ|Vadodara|chemicals_dyes,electrical_eq,engineering
GJ|Rajkot|engineering,castings_forgings,pumps_valves,auto_components
GJ|Morbi|ceramics,glass,packaging_corrugated
GJ|Jamnagar|nonferrous_brass,refining
GJ|Bharuch|chemicals_dyes,specialty_chemicals
GJ|Ankleshwar|chemicals_dyes,agrochemicals,pharma
GJ|Vapi|chemicals_dyes,paper,pharma
GJ|Bhavnagar|shipbuilding,steel_rerolling,diamonds
GJ|Alang|shipbuilding
GJ|Kandla-Gandhidham|ports,logistics_warehousing,edible_oil,plywood_laminates
GJ|Mundra|ports,power,edible_oil
GJ|Unjha|spices
GJ|Veraval|seafood_processing
GJ|Sanand|vehicle_oem,auto_components
GJ|Dahej|petrochem,chemicals_dyes
GJ|Halol|auto_components,two_wheelers
GJ|Mehsana|dairy_products,engineering
GJ|Anand|dairy_products
GJ|Gondal|cotton_ginning,edible_oil
DN|Silvassa|plastics,manmade_fibres,electrical_eq
DN|Daman|plastics,pharma
MH|Mumbai|wholesale_trade,diamond_trading,nbfc,commercial_real_estate,shipping
MH|Pune|auto_components,vehicle_oem,engineering,software_it
MH|Chakan|vehicle_oem,auto_components
MH|Nashik|fruits_veg,engineering,electrical_eq
MH|Aurangabad|auto_components,pharma,two_wheelers
MH|Bhiwandi|handloom_powerloom,logistics_warehousing
MH|Malegaon|handloom_powerloom
MH|Ichalkaranji|handloom_powerloom,cotton_textiles
MH|Solapur|home_textiles,sugar
MH|Kolhapur|sugar,castings_forgings
MH|Nagpur|logistics_warehousing,engineering,fruits_veg
MH|Thane-Belapur|chemicals_dyes,engineering
MH|Tarapur|chemicals_dyes,steel_rerolling
MH|Jalna|steel_rerolling,seeds
MH|Sangli|sugar,spices
KA|Bengaluru|software_it,electronics,defence_aerospace,apparel,machine_tools
KA|Mysuru|silk_weaving,auto_components,tourism_hotels
KA|Belagavi|castings_forgings,sugar
KA|Hubballi-Dharwad|engineering,cotton_ginning
KA|Ballari|metals,iron_ore_mining
KA|Mangaluru|refining,seafood_processing,cashew
KA|Chikkamagaluru|coffee
KA|Davangere|cotton_textiles,rice_milling
KA|Tumakuru|engineering,food_processing
GA|Vasco-Margao|iron_ore_mining,pharma,shipbuilding
GA|Panaji|tourism_hotels,pharma
KL|Kochi|seafood_processing,spices,refining,shipbuilding
KL|Kollam|cashew,coir_products
KL|Alappuzha|coir_products,seafood_processing
KL|Thrissur|gold_jewellery,ayush_herbal
KL|Kottayam|plantation_rubber,rubber_tyres
KL|Thiruvananthapuram|it_bpo,tourism_hotels
KL|Kozhikode|wooden_furniture,plywood_laminates
TN|Tiruppur|hosiery_knitwear,apparel,cotton_textiles
TN|Coimbatore|pumps_valves,textile_machinery,cotton_textiles,castings_forgings
TN|Chennai|vehicle_oem,auto_components,electronics,software_it,leather
TN|Sriperumbudur|mobile_assembly,auto_components
TN|Hosur|two_wheelers,auto_components,electronics
TN|Sivakasi|fireworks_matches,printing_publishing
TN|Karur|home_textiles
TN|Erode|textile_processing,spices,handloom_powerloom
TN|Salem|steel_rerolling,sago_proxy,poultry_farming
TN|Namakkal|trucking_fleet,poultry_farming
TN|Madurai|rubber_tyres,handloom_powerloom
TN|Vellore-Ambur|leather_tanning,footwear
TN|Tuticorin|ports,seafood_processing,power
TN|Kanchipuram|silk_weaving
TN|Krishnagiri|fruits_veg
TN|Nilgiris|tea
PY|Puducherry|electrical_eq,pharma,tourism_hotels
TS|Hyderabad|pharma,api_bulk_drugs,software_it,defence_aerospace,residential_real_estate
TS|Patancheru|api_bulk_drugs,chemicals_dyes
TS|Nizamabad|spices,tobacco
TS|Warangal|cotton_ginning,rice_milling
AP|Visakhapatnam|metals,ports,pharma,refining
AP|Kakinada|rice_milling,seafood_processing,fertiliser
AP|Bhimavaram|seafood_processing,fisheries_aquaculture
AP|Nellore|seafood_processing,power
AP|Guntur|spices,tobacco,cotton_ginning
AP|Sri City|electronics,electrical_eq,food_processing
AP|Chittoor|fruits_veg,dairy_products
AP|Anantapur|vehicle_oem,renewables
LA|Leh|tourism_hotels,handicrafts
AN|Port Blair|tourism_hotels,fisheries_aquaculture
"""


def main():
    cfg = json.loads((ROOT / "lending_config.json").read_text())
    scored = {s["id"]: s for s in cfg["sectors"]}
    inds = []
    for s in cfg["sectors"]:
        inds.append({"id": s["id"], "name": s["name"], "group": s.get("group"), "parent": s["id"], "mapping": "direct",
                     "nic": s.get("iip_nic"), "series": {"rbi": s.get("rbi_row"), "iip": s.get("iip_nic"), "exports": s.get("export_row")}})
    for line in PROXY.strip().splitlines():
        i, n, g, p, nic, f = line.split("|")
        assert p in scored, p
        ps = scored[p]
        inds.append({"id": i, "name": n, "group": g, "parent": p, "mapping": "proxy: parent sector", "nic": nic, "focus": f,
                     "series": {"rbi": ps.get("rbi_row"), "iip": ps.get("iip_nic"), "exports": ps.get("export_row")}})
    ids = {x["id"] for x in inds}
    assert len(ids) == len(inds)
    alias = {"soya_proxy": "edible_oil", "automotive_proxy": "auto_components", "sago_proxy": "food_processing"}
    states = {s["code"] for s in cfg["states"]}
    cities = []
    for line in CITIES.strip().splitlines():
        st, name, hubs = line.split("|")
        assert st in states, st
        hs = []
        for h in hubs.split(","):
            h = alias.get(h, h)
            assert h in ids, h
            if h not in hs:
                hs.append(h)
        cid = st.lower() + "_" + "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")
        cities.append({"id": cid, "name": name, "state": st, "hubs": hs})
    (ROOT / "industries.json").write_text(json.dumps({"_doc": "Industry catalogue. 'direct' = scored on its own RBI/IIP/export series; 'proxy: parent sector' = uses the nearest parent scored sector. focus = analytical framing, not data.", "industries": inds}, indent=1, ensure_ascii=False))
    (ROOT / "cities.json").write_text(json.dumps({"_doc": "Major industrial cities/clusters per state; hubs = industries the city is a known hub for (local briefs are precomputed for these pairs).", "cities": cities}, indent=1, ensure_ascii=False))
    print(len(inds), "industries;", len(cities), "cities;", sum(len(c["hubs"]) for c in cities), "hub pairs;", len({c['state'] for c in cities}), "states")


if __name__ == "__main__":
    main()
