"""Phase-1 witness universe: 30 listed companies, weighted to Gujarat-linked supply chains.
channel = primary economic channel the company 'testifies' about. common_factor groups
companies whose signals share a driver (they count once in breadth)."""
UNIVERSE = [
 # sym, name, sector, channel, common_factor, gujarat_link, relationships
 ("ARVIND","Arvind","Textiles","export","textile_cotton","Ahmedabad denim/garments",{"suppliers":["cotton ginners"],"customers":["global apparel brands"],"peers":["WELSPUNLIV"]}),
 ("WELSPUNLIV","Welspun Living","Home textiles","export","textile_cotton","Anjar (Kutch) plant",{"suppliers":["cotton yarn"],"customers":["US retailers"],"peers":["ARVIND"]}),
 ("FILATEX","Filatex India","Polyester yarn (MMF)","input_cost","polyester_chain","Dahej plant; supplies Surat weavers",{"suppliers":["PTA/MEG (RELIANCE)"],"customers":["Surat weavers"],"peers":["ARVIND"]}),
 ("ATUL","Atul","Chemicals & dyes","export","specialty_chem","Valsad",{"suppliers":["petrochemicals"],"customers":["textiles, agro, pharma"],"peers":["DEEPAKNTR","AARTIIND"]}),
 ("DEEPAKNTR","Deepak Nitrite","Intermediates","input_cost","specialty_chem","Vadodara/Dahej",{"suppliers":["benzene, propylene"],"customers":["dyes, pharma"],"peers":["AARTIIND","ATUL"]}),
 ("AARTIIND","Aarti Industries","Benzene intermediates","input_cost","specialty_chem","Vapi/Bharuch",{"suppliers":["benzene"],"customers":["agro, pharma, dyes"],"peers":["DEEPAKNTR"]}),
 ("NAVINFLUOR","Navin Fluorine","Fluorochemicals","export","specialty_chem","Surat/Dahej",{"suppliers":["fluorspar"],"customers":["pharma, agro, refrigerants"],"peers":["ATUL"]}),
 ("KAJARIACER","Kajaria Ceramics","Tiles","demand","building_materials","Morbi JV units",{"suppliers":["PETRONET (LNG)","clay"],"customers":["dealers, real estate"],"peers":["SOMANYCERA","ASIANTILES"]}),
 ("SOMANYCERA","Somany Ceramics","Tiles","demand","building_materials","Morbi associate units",{"suppliers":["PETRONET"],"customers":["dealers"],"peers":["KAJARIACER"]}),
 ("ASIANTILES","Asian Granito","Tiles","demand","building_materials","Himmatnagar/Morbi",{"suppliers":["PETRONET"],"customers":["dealers"],"peers":["KAJARIACER"]}),
 ("PETRONET","Petronet LNG","LNG import terminal","input_cost","energy","Dahej terminal; gas for Morbi/Gujarat industry (Gujarat Gas not served by NSE results API)",{"suppliers":["Qatar LNG"],"customers":["GAIL, Gujarat Gas, Morbi ceramics"],"peers":[]}),
 ("ULTRACEMCO","UltraTech Cement","Cement","demand","building_materials","Gujarat plants",{"suppliers":["coal, petcoke"],"customers":["housing, infra"],"peers":["AMBUJACEM","JKLAKSHMI"]}),
 ("AMBUJACEM","Ambuja Cements","Cement","demand","building_materials","Kodinar plant",{"suppliers":["coal"],"customers":["housing"],"peers":["ULTRACEMCO"]}),
 ("JKLAKSHMI","JK Lakshmi Cement","Cement","demand","building_materials","Kalol/Surat grinding",{"suppliers":["coal"],"customers":["housing"],"peers":["ULTRACEMCO"]}),
 ("ASTRAL","Astral","Pipes","demand","building_materials","Ahmedabad",{"suppliers":["PVC resin"],"customers":["plumbing, agri"],"peers":[]}),
 ("PIDILITIND","Pidilite","Adhesives","demand","consumer","Vapi/Bharuch plants",{"suppliers":["VAM"],"customers":["carpenters, retail"],"peers":[]}),
 ("ASIANPAINT","Asian Paints","Paints","demand","consumer","Ankleshwar plant",{"suppliers":["TiO2, crude derivatives"],"customers":["retail, housing"],"peers":["PIDILITIND"]}),
 ("MARUTI","Maruti Suzuki","Passenger vehicles","demand","auto","Hansalpur (Gujarat)",{"suppliers":["MOTHERSON","BHARATFORG"],"customers":["households"],"peers":[]}),
 ("ASHOKLEY","Ashok Leyland","Commercial vehicles","demand","auto","CV demand = freight/capex proxy",{"suppliers":["forgings"],"customers":["fleet operators"],"peers":["MARUTI"]}),
 ("MOTHERSON","Samvardhana Motherson","Auto components","export","auto","Gujarat units",{"suppliers":["plastics, copper"],"customers":["MARUTI, global OEMs"],"peers":["BHARATFORG"]}),
 ("BHARATFORG","Bharat Forge","Forgings","export","auto","Sanand supply chain",{"suppliers":["steel"],"customers":["CV OEMs, US trucks"],"peers":["MOTHERSON"]}),
 ("LT","Larsen & Toubro","EPC/capital goods","policy","capex","Hazira heavy engineering",{"suppliers":["steel, cement"],"customers":["govt, private capex"],"peers":["ELECON","THERMAX"]}),
 ("ELECON","Elecon Engineering","Gears/MHE","demand","capex","Vallabh Vidyanagar",{"suppliers":["steel castings"],"customers":["cement, steel, power"],"peers":["THERMAX"]}),
 ("THERMAX","Thermax","Boilers/energy equipment","demand","capex","Gujarat projects",{"suppliers":["steel"],"customers":["chemicals, process industry"],"peers":["ELECON"]}),
 ("CONCOR","Container Corporation","Rail logistics","demand","trade_logistics","Gujarat ports hinterland",{"suppliers":["Railways"],"customers":["exporters/importers"],"peers":["GPPL","ADANIPORTS"]}),
 ("GPPL","Gujarat Pipavav Port","Port","export","trade_logistics","Pipavav",{"suppliers":[],"customers":["shipping lines"],"peers":["ADANIPORTS"]}),
 ("ADANIPORTS","Adani Ports & SEZ","Ports","export","trade_logistics","Mundra",{"suppliers":[],"customers":["shipping, EXIM"],"peers":["GPPL"]}),
 ("SHRIRAMFIN","Shriram Finance","NBFC - CV/MSME","credit","credit_nbfc","Large Gujarat CV book",{"suppliers":["banks, bond market"],"customers":["truckers, MSMEs"],"peers":["CHOLAFIN"]}),
 ("CHOLAFIN","Cholamandalam Finance","NBFC - vehicle/SME","credit","credit_nbfc","SME LAP",{"suppliers":["banks"],"customers":["MSMEs, vehicle buyers"],"peers":["SHRIRAMFIN"]}),
 ("BAJFINANCE","Bajaj Finance","NBFC - consumer/SME","credit","credit_nbfc","Consumer & SME loans",{"suppliers":["banks, CP market"],"customers":["households, SMEs"],"peers":["CHOLAFIN"]}),
]
LENDERS = {"SHRIRAMFIN","CHOLAFIN","BAJFINANCE"}
