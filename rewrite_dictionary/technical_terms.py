"""공식 자료의 전문 용어와 재질 약어를 검색용으로 풀이한다."""

import re
from collections.abc import Callable
from functools import cache

TECHNICAL_SOURCES = {
    "plastic_markings": (
        None,
        "한국환경공단 분리배출표시제도",
        "https://www.keco.or.kr/web/lay1/S1T183C1049/contents.do",
    ),
    "marking_rules": (
        None,
        "분리배출 표시에 관한 지침",
        "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000283152",
    ),
    "polymer_nomenclature": (
        None,
        "식품의약품안전처 식품용 기구 및 용기·포장 공전의 재질별 명칭",
        "https://dl.nanet.go.kr/detail/MONO1202050908",
    ),
    "food_contact_material_names": (
        None,
        "식품의약품안전처 식품용 기구 및 용기·포장 공전의 합성수지 재질 명칭",
        "https://www.law.go.kr/LSW/flDownload.do?bylClsCd=&flSeq=141486339",
    ),
    "mfds_packaging_standard": (
        None,
        "식품의약품안전처 기구 및 용기·포장의 기준 및 규격 제2026-72호",
        "https://www.law.go.kr/LSW/flDownload.do?flSeq=171063955",
    ),
    "pla_material_name": (
        None,
        "농림축산식품부 폴리젖산 재질 명칭 자료",
        "https://www.mafra.go.kr/bbs/mafra/68/239258/download.do",
    ),
    "packaging_component_marking": (
        None,
        "한국환경공단 다중포장재의 일괄표시 예시",
        "https://www.keco.or.kr/group01/lay1/S296T497C509/contents.do",
    ),
    "packaging_recyclability_grade": (
        None,
        "한국환경공단 포장재 재질·구조 평가 제도",
        "https://www.keco.or.kr/web/lay1/S1T183C1055/contents.do",
    ),
    "polyethylene_names": (
        None,
        "기후에너지환경부 설명 자료의 PE·HDPE·LDPE 명칭",
        "https://www.mcee.go.kr/home/web/board/read.do?boardId=1396730&boardMasterId=1",
    ),
    "packaging_materials": (
        None,
        "자원재활용법 시행령 별표 6의 제품·포장재별 재질 명칭",
        "https://www.law.go.kr/DRF/flDownload.do?flSeq=161063347",
    ),
    "wood_products": (
        None,
        "목재의 지속가능한 이용에 관한 법률 시행령 제19조의4",
        "https://www.law.go.kr/lsLinkCommonInfo.do?lspttninfSeq=58258",
    ),
    "fiberboard_spec": (
        None,
        "국립산림과학원 섬유판 부속서의 MDF 명칭",
        "https://www.law.go.kr/LSW/flDownload.do?bylClsCd=200209&flSeq=132408513",
    ),
}

# 약어, 재질 검색어, 약어가 나오는 문서, 해석 문맥
MATERIAL_CODES = (
    (
        "PET",
        "폴리에틸렌테레프탈레이트",
        ("packaging_materials", "plastic_markings"),
        "포장재의 재질 표시. 색상과 병·용기 형상은 별도로 확인.",
    ),
    (
        "PE",
        "폴리에틸렌",
        ("polymer_nomenclature", "seodaemun_recycling"),
        "재질 약어. 고밀도·저밀도 표기가 있는지 별도로 확인.",
    ),
    (
        "HDPE",
        "고밀도 폴리에틸렌",
        ("plastic_markings", "polyethylene_names"),
        "포장재의 재질 표시.",
    ),
    (
        "LDPE",
        "저밀도 폴리에틸렌",
        ("plastic_markings", "polyethylene_names"),
        "포장재의 재질 표시.",
    ),
    (
        "PP",
        "폴리프로필렌",
        ("polymer_nomenclature", "plastic_markings"),
        "포장재의 재질 표시.",
    ),
    (
        "PS",
        "폴리스티렌",
        ("polymer_nomenclature", "plastic_markings"),
        "재질 약어. 발포 여부는 별도로 확인.",
    ),
    (
        "PVC",
        "폴리염화비닐",
        ("polymer_nomenclature", "seodaemun_recycling"),
        "재질 문맥에서 해석. 파이프·포장재 등 품목 정보를 함께 유지.",
    ),
    (
        "PC",
        "폴리카보네이트",
        ("polymer_nomenclature", "seodaemun_recycling"),
        "재질 문맥에서만 해석. 컴퓨터 본체·주변기기는 기존 품목 검색을 사용.",
    ),
    (
        "PSP",
        "폴리스티렌페이퍼",
        ("packaging_materials", "seodaemun_recycling"),
        "포장재 명칭. 발포폴리스티렌 완충재와 구별.",
    ),
    (
        "ABS",
        "아크릴로니트릴-부타디엔-스티렌 공중합체",
        ("food_contact_material_names",),
        "수지 명칭. 자동차의 ABS 부품이나 센서와 구별.",
    ),
    (
        "PA",
        "폴리아미드",
        ("food_contact_material_names",),
        "재질 표시에 쓴 약어. 물건의 형태와 다른 재질의 부착 여부를 함께 본다.",
    ),
    (
        "PU",
        "폴리우레탄",
        ("food_contact_material_names",),
        "폼·코팅 등에 표기되는 재질명. 실제 사용 형태를 함께 본다.",
    ),
    (
        "EVA",
        "에틸렌-초산비닐 공중합체",
        ("food_contact_material_names",),
        "폼·매트 등에서 볼 수 있는 재질 표기.",
    ),
    (
        "PVDC",
        "폴리염화비닐리덴",
        ("food_contact_material_names",),
        "필름·래핑 재질 표기. PVC와 구분.",
    ),
    (
        "PLA",
        "폴리젖산",
        ("pla_material_name",),
        "용기 등에 적힌 재질명. 생분해 표시는 분리배출 대상의 판정 근거와 별개다.",
    ),
    ("EPS", "발포폴리스티렌", ("packaging_materials",), "발포합성수지의 한 종류."),
    ("EPP", "발포폴리프로필렌", ("packaging_materials",), "발포합성수지의 한 종류."),
    ("EPE", "발포폴리에틸렌", ("packaging_materials",), "발포합성수지의 한 종류."),
    (
        "PET-G",
        "글리콜변성 PET 수지",
        ("plastic_markings",),
        "붙임표가 포함된 재질명. PET만 적힌 표시와 구별.",
    ),
    (
        "OTHER",
        "기타 재질 표시",
        ("plastic_markings", "marking_rules"),
        "표시 목록 밖의 단일재질과 일부 혼합·복합재질을 포함. 실제 재질과 배출 기준은 별도 확인.",
    ),
    (
        "MDF",
        "중밀도섬유판",
        ("wood_products", "fiberboard_spec"),
        "목재 섬유 계열 판재. 원목·합판과 구별.",
    ),
    *(
        (
            code,
            name,
            ("mfds_packaging_standard",),
            "재질·수지 등 명시적 재질 문맥에서 해석.",
        )
        for code, name in (
            ("PBS", "부틸렌숙시네이트 공중합체"),
            ("PBSA", "부틸렌숙시네이트-아디페이트 공중합체"),
            ("PBAT", "폴리부틸렌아디페이트테레프탈레이트"),
            ("PBT", "폴리부틸렌테레프탈레이트"),
            ("POM", "폴리아세탈"),
        )
    ),
)

# 표준 검색어, 주민이 이해할 풀이, 같이 볼 품목 또는 용어, 참고 자료
TECHNICAL_TERMS = {
    "합성수지·포장재": (
        (
            "합성수지",
            "플라스틱 제품과 포장에 쓰이는 여러 수지 재료를 이르는 말.",
            ("합성수지 용기", "비닐(필름)류", "발포합성수지 포장재"),
            ("seodaemun_recycling", "plastic_markings"),
        ),
        (
            "합성수지 용기",
            "플라스틱 용기·통을 검색할 때 참고하는 조례 표기.",
            ("트레이류", "단일재질"),
            ("seodaemun_recycling", "songpa_recycling_guide"),
        ),
        (
            "트레이류",
            "식품 등을 담는 받침이나 쟁반 모양 용기.",
            ("합성수지 용기", "다중포장재"),
            ("seodaemun_recycling", "plastic_markings"),
        ),
        (
            "비닐(필름)류",
            "얇은 필름이나 시트 형태인 봉지·포장 비닐을 찾는 말.",
            ("필름·시트형 포장재",),
            ("seodaemun_recycling", "plastic_markings"),
        ),
        (
            "필름·시트형 포장재",
            "얇은 막 또는 얇은 판 모양으로 만든 포장재.",
            ("비닐(필름)류", "복합재질 포장재"),
            ("plastic_markings", "packaging_materials"),
        ),
        (
            "발포합성수지 포장재",
            "기포를 넣어 가볍게 만든 수지 포장재. EPS·EPP·EPE 등 종류가 있다.",
            ("스티로폼 완충재", "발포폴리스티렌"),
            ("seodaemun_recycling", "packaging_materials"),
        ),
        (
            "스티로폼 완충재",
            "딱딱한 발포 포장재의 생활 표현. 제품 포장인지와 오염·코팅을 함께 본다.",
            ("발포합성수지 포장재",),
            ("seodaemun_recycling",),
        ),
        (
            "단일재질",
            "한 종류의 재질로 된 경우를 나타내는 표현.",
            ("복합재질 포장재",),
            ("marking_rules", "packaging_materials"),
        ),
        (
            "복합재질 포장재",
            "두 종류 이상의 재료를 함께 써서 만든 포장재.",
            ("다중포장재", "도포·첩합 등", "기타 재질 표시"),
            ("marking_rules", "plastic_markings"),
        ),
        (
            "다중포장재",
            "한 제품을 포장하는 받침·겉포장 또는 분리 가능한 본체·뚜껑 같은 구성.",
            ("복합재질 포장재",),
            ("marking_rules",),
        ),
        (
            "도포·첩합 등",
            "표면에 덧바르거나 다른 재료 층이 붙은 포장재에 쓰이는 표시 문구.",
            ("복합재질 포장재", "기타 재질 표시"),
            ("marking_rules", "plastic_markings"),
        ),
        (
            "무색 PET병",
            "색이 없는 PET병을 찾는 말. 음료·먹는샘물 용기인지도 함께 본다.",
            ("PET병", "유색 PET병"),
            ("seodaemun_recycling", "songpa_recycling_guide"),
        ),
        (
            "유색 PET병",
            "색이 있는 PET병을 찾는 말.",
            ("PET병", "무색 PET병"),
            ("seodaemun_recycling", "packaging_materials"),
        ),
        (
            "종이팩",
            "우유나 두유 등을 담는 팩의 품목명. 포장 종류를 함께 확인한다.",
            ("살균팩", "멸균팩"),
            ("seodaemun_recycling",),
        ),
        (
            "살균팩",
            "살균한 음료에 쓰이는 종이팩의 유형.",
            ("종이팩", "멸균팩"),
            ("seodaemun_recycling", "plastic_markings"),
        ),
        (
            "멸균팩",
            "멸균한 내용물을 담는 종이팩의 유형. 안쪽 층과 팩 표기를 확인한다.",
            ("종이팩", "살균팩"),
            ("seodaemun_recycling", "plastic_markings"),
        ),
        (
            "알루미늄박",
            "얇게 만든 알루미늄 호일. 다른 재질과 붙어 있는지 확인한다.",
            ("복합재질 포장재",),
            ("seodaemun_recycling",),
        ),
        (
            "감열지",
            "열로 글자가 나타나는 종이. 영수증에서 볼 수 있다.",
            ("영수증 감열지",),
            ("seodaemun_recycling",),
        ),
    ),
    "포장재 구조·재질": (
        (
            "폐합성수지",
            "폐기된 합성수지를 찾는 전문 용어. 가정 배출인지, 사업장이나 제조공정에서 나온 것인지 함께 본다.",
            ("합성수지", "합성수지 용기", "공사장생활폐기물"),
            ("songpa_rules",),
        ),
        (
            "합성수지비닐류",
            "조례의 분리배출 안내에서 비닐·필름 등 얇은 합성수지 형태를 찾을 때 쓰는 명칭.",
            ("비닐(필름)류", "필름·시트형 포장재"),
            ("seodaemun_recycling",),
        ),
        (
            "포장재 일괄표시",
            "포장재의 한 곳에 본체·뚜껑·라벨 등 구성 부분의 표시를 모아 적는 방식.",
            ("다중포장재", "단일재질", "복합재질 포장재"),
            ("marking_rules", "packaging_component_marking"),
        ),
        (
            "재활용 용이성 등급",
            "포장재의 재질과 구조를 평가한 결과를 찾는 용어.",
            ("포장재 일괄표시", "복합재질 포장재"),
            ("packaging_recyclability_grade",),
        ),
        (
            "폴리젖산",
            "PLA 표기에 대응하는 수지 이름. 폴리유산이라는 표현도 쓰인다.",
            ("생분해성 플라스틱", "합성수지"),
            ("pla_material_name",),
        ),
        (
            "생분해성 플라스틱",
            "일정한 환경 조건에서 생물 작용으로 분해되는 소재를 가리키는 용어.",
            ("폴리젖산", "기타 재질 표시"),
            ("pla_material_name", "marking_rules"),
        ),
        (
            "폴리아미드",
            "PA 표기에서 찾는 수지 계열의 명칭.",
            ("합성수지", "필름·시트형 포장재"),
            ("food_contact_material_names",),
        ),
        (
            "폴리우레탄",
            "PU 표기에 대응하는 수지 이름. 폼이나 코팅 등 사용 형태를 함께 확인한다.",
            ("합성수지", "발포합성수지 포장재"),
            ("food_contact_material_names",),
        ),
        (
            "에틸렌-초산비닐 공중합체",
            "EVA라는 재질 약어에 대응하는 정식 명칭.",
            ("합성수지", "발포합성수지 포장재"),
            ("food_contact_material_names",),
        ),
        (
            "폴리염화비닐리덴",
            "PVDC에 대응하는 재질명. PVC 표기와 구별한다.",
            ("폴리염화비닐", "필름·시트형 포장재"),
            ("food_contact_material_names",),
        ),
    ),
    "금속·전기·조명": (
        (
            "고철류",
            "철을 주재료로 하는 폐금속을 찾는 분류명.",
            ("철판", "비철금속"),
            ("seodaemun_recycling",),
        ),
        (
            "비철금속",
            "알루미늄이나 구리 등 철 이외의 금속을 묻는 말.",
            ("고철류", "알루미늄 샷시류"),
            ("seodaemun_recycling",),
        ),
        (
            "폐전지류",
            "다 쓴 전지를 통틀어 찾는 말. 충전 여부와 전지 종류가 관계된다.",
            ("전지류", "폐납산배터리", "리튬이차전지"),
            ("songpa_recycling_guide",),
        ),
        (
            "리튬이차전지",
            "리튬 계열의 다시 충전할 수 있는 전지.",
            ("폐전지류", "리튬1차 전지"),
            ("songpa_recycling_guide",),
        ),
        (
            "리튬1차 전지",
            "리튬 계열의 1차 전지. 충전식 리튬이차전지와 구분한다.",
            ("리튬이차전지",),
            ("seodaemun_recycling", "songpa_recycling_guide"),
        ),
        (
            "폐납산배터리",
            "사용이 끝난 납산 방식의 배터리.",
            ("폐전지류",),
            ("songpa_recycling_guide",),
        ),
        (
            "등기구",
            "램프를 고정하거나 전원을 연결하는 조명기구 본체.",
            ("조명기구", "LED 등기구", "전등 케이스"),
            ("songpa_item_standards", "seodaemun_appliance_guide"),
        ),
        (
            "형광등 안정기",
            "형광등의 전류를 조절하는 부품. 램프 본체와 구분한다.",
            ("형광등", "안정기 내장형 형광등"),
            ("seodaemun_recycling",),
        ),
        (
            "직관형 형광등",
            "막대처럼 길고 곧은 형광등.",
            ("형광등", "환형 형광등", "직관형 LED 램프"),
            ("seodaemun_recycling", "songpa_recycling_guide"),
        ),
        (
            "환형 형광등",
            "고리 모양의 형광등.",
            ("형광등", "원반형 LED 등"),
            ("seodaemun_recycling", "songpa_recycling_guide"),
        ),
    ),
    "목재·공사": (
        (
            "순수목재",
            "서대문구 수수료 표에 나오는 목재 항목. 합판·코팅·완성 가구 여부를 따로 본다.",
            ("목재", "폐목재", "합판", "원목 가구"),
            ("seodaemun_bulky",),
        ),
        (
            "합판",
            "얇은 나무 층을 여러 겹 붙인 판.",
            ("나무 판자", "중밀도섬유판"),
            ("wood_products",),
        ),
        (
            "집성재",
            "나무 조각이나 층을 접착해 만든 목재.",
            ("합판", "목재"),
            ("wood_products",),
        ),
        (
            "파티클보드",
            "나무의 작은 조각을 눌러 붙여 만든 판재.",
            ("중밀도섬유판", "합판"),
            ("wood_products",),
        ),
        (
            "폐목재",
            "버려지는 목재. 공사 중 발생했는지와 재질 상태를 함께 본다.",
            ("목재", "원목 가구", "공사장생활폐기물"),
            ("seodaemun_ordinance", "construction_waste_types"),
        ),
        (
            "폐보드류",
            "공사 뒤 나온 보드 형태의 폐자재를 찾는 법령 항목.",
            ("공사장생활폐기물", "폐판넬"),
            ("construction_waste_types",),
        ),
        (
            "공사장생활폐기물",
            "수리·리모델링 등 공사 과정에서 나온 폐기물의 조례 용어. 발생 경위와 양이 관계된다.",
            ("건설폐기물", "폐목재", "폐콘크리트"),
            ("seodaemun_ordinance", "songpa_construction_waste"),
        ),
        (
            "건설폐기물",
            "건설공사에서 발생한 폐기물 중 해당 법령의 적용 범위에 드는 것.",
            ("공사장생활폐기물", "폐타일"),
            ("construction_waste_types",),
        ),
    ),
    "사업장·실험·농업": (
        (
            "지정폐기물",
            "종류·발생 시설·성상 등이 법령 기준에 드는 폐기물.",
            ("폐유기용제", "폐산", "사업장폐기물"),
            ("designated_waste_types",),
        ),
        (
            "폐유기용제",
            "사용이 끝난 유기용제. 원래 물질과 성상을 확인한다.",
            ("폐시약", "실험폐액"),
            ("designated_waste_types", "lab_waste_guide"),
        ),
        (
            "폐시약",
            "연구·실험 후 폐기하는 시약. 내용물이 남은 경우와 빈 시약 용기를 구분한다.",
            ("실험폐액", "빈 시약병"),
            ("lab_waste_guide", "lab_liquid_guide"),
        ),
        (
            "실험폐액",
            "실험 과정에서 나온 액체 폐기물.",
            ("폐시약", "실험폐수"),
            ("lab_liquid_guide",),
        ),
        (
            "손상성폐기물",
            "주사바늘 등 법령에서 별도로 분류하는 의료폐기물 용어.",
            ("의료폐기물", "주사바늘"),
            ("medical_waste_types",),
        ),
        (
            "의료폐기물",
            "진료·검사 등에서 발생하여 법령 기준에 해당하는 폐기물.",
            ("손상성폐기물", "폐혈액백"),
            ("medical_waste_types", "medical_facility_scope"),
        ),
        (
            "폐농약",
            "쓰고 남았거나 폐기하려는 농약. 남은 약품과 빈 포장을 구분한다.",
            ("빈 농약병", "농약 용기"),
            ("pesticide_faq", "farming_container_guide"),
        ),
        (
            "영농폐비닐",
            "농업에 사용한 뒤 버리는 비닐. 하우스·멀칭 등 사용 용도를 함께 본다.",
            ("시설하우스 비닐", "멀칭 비닐"),
            ("farming_container_guide",),
        ),
        (
            "다량배출사업장",
            "법령·조례에서 정한 업종이나 규모 등의 요건에 해당하는 배출 사업장.",
            ("집단급식소", "음식물류폐기물"),
            ("songpa_food_business",),
        ),
    ),
    "배출 안내·수거": (
        (
            "생활폐기물",
            "법령에서 사업장폐기물과 구분하는 생활 배출 폐기물 용어.",
            ("사업장폐기물", "일반쓰레기"),
            ("seodaemun_ordinance", "songpa_ordinance"),
        ),
        (
            "사업장생활계폐기물",
            "사업장에서 나오지만 성질이 생활폐기물과 비슷한 폐기물을 찾는 용어.",
            ("생활폐기물", "사업장폐기물"),
            ("seodaemun_ordinance",),
        ),
        (
            "특수규격봉투",
            "일반 봉투에 담기 어려운 대상품목용으로 조례에서 따로 둔 봉투.",
            ("규격봉투", "불연성 쓰레기"),
            ("seodaemun_ordinance", "songpa_waste_guide"),
        ),
        (
            "납부필증",
            "수수료를 냈음을 표시하는 증표.",
            ("음식물류전용용기납부필증",),
            ("songpa_ordinance", "seodaemun_food_supplies"),
        ),
        (
            "종량제봉투",
            "배출량에 따라 수수료를 내는 제도에 쓰는 지정 봉투.",
            ("일반규격봉투", "특수규격봉투"),
            ("seodaemun_ordinance", "songpa_ordinance"),
        ),
        (
            "빈용기보증금",
            "보증금 대상 빈 병을 돌려줄 때 환급되는 보증금 제도.",
            ("유리병",),
            ("seodaemun_recycling", "songpa_recycling_notes"),
        ),
        (
            "문전수거",
            "정해진 배출장소 중 주택이나 건물 앞에서 수거하는 방식.",
            ("대형폐기물",),
            ("seodaemun_filing_guide", "songpa_recycling_guide"),
        ),
        (
            "민원성 마대",
            "송파구 안내에서 일부 품목에 안내되는 특수규격봉투의 명칭.",
            ("특수규격봉투", "불연성 쓰레기"),
            ("songpa_waste_guide",),
        ),
    ),
}

_MATERIAL_NAMES = {code: term for code, term, _, _ in MATERIAL_CODES}
_CODE_PATTERN = re.compile(
    r"(?<![\w-])(?P<code>(?ai:"
    + "|".join(map(re.escape, sorted(_MATERIAL_NAMES, key=len, reverse=True)))
    + r"))(?![a-zA-Z0-9_-])",
)
_MARK_BEFORE = re.compile(
    r"""(?:재질(?:[ \t]*표시)?|소재|표기|각인|마크)(?:[은는이가])?[ \t]*[:=]?[ \t]*["'“‘(]?\Z"""
)
_MARK_AFTER = re.compile(
    r"""["'”’)]?[ \t]*(?:재질|수지|소재|표시|표기|각인|마크|플라스틱|로[ \t]*(?:된|표시))"""
)
_COMPONENT_BEFORE = re.compile(
    r"""(?:뚜껑|마개|라벨|본체|몸체|안쪽|겉면)[ \t]*(?:[:=][ \t]*["'“‘(]?|\([ \t]*)\Z"""
)
_EXPLICIT_MATERIAL_BEFORE = re.compile(
    r"""(?:재질(?:[ \t]*표시)?|소재)(?:[은는이가])?[ \t]*[:=]?[ \t]*["'“‘(]?\Z"""
)
_EXPLICIT_MATERIAL_AFTER = re.compile(r"""["'”’)]?[ \t]*(?:재질|수지|소재|플라스틱)""")
_EXPLICIT_MATERIAL_CODES = ("PC", "ABS", "PBS", "PBSA", "PBAT", "PBT", "POM")
_EXCLUDED_PREFIX_PATTERNS = {"PET": re.compile(r"글리콜[ \t]*변성[ \t]*\Z")}
_UPPERCASE_ITEM_SUFFIX_PATTERNS = {"OTHER": re.compile(r"\s*(?:비닐|포장재)")}
_ITEM_AFTER = {
    code: re.compile(r"\s*(?:" + labels + r")")
    for code, labels in {
        "PET": "병|용기|트레이|필름|포장재",
        "PET-G": "병|용기|트레이|필름|포장재",
        "PE": "필름|용기|비닐|포장재",
        "HDPE": "뚜껑|마개|용기|병|포장재",
        "LDPE": "필름|비닐|봉투|포장재",
        "PP": "뚜껑|마개|용기|컵|트레이|마대|포장재",
        "PS": "용기|컵|트레이|포장재",
        "PVC": "파이프|배관|필름|용기|포장재",
        "PSP": "용기|트레이|포장재",
        "PA": "필름|포장재",
        "PU": "폼|코팅|스펀지",
        "EVA": "폼|매트",
        "PVDC": "랩|필름|포장재",
        "PLA": "컵|용기|필름|포장재",
        "EPS": "완충재|포장재",
        "EPP": "완충재|포장재",
        "EPE": "완충재|포장재",
        "MDF": "판재|선반|가구|보드",
    }.items()
}


def material_matching_rules() -> dict:
    """재질 확장에 필요한 실제 문맥과 약어별 예외를 내보낸다."""
    return {
        "code_pattern": _CODE_PATTERN.pattern,
        "explicit_material_codes": _EXPLICIT_MATERIAL_CODES,
        "context_patterns": {
            "mark_before": _MARK_BEFORE.pattern,
            "mark_after": _MARK_AFTER.pattern,
            "component_before": _COMPONENT_BEFORE.pattern,
            "explicit_material_before": _EXPLICIT_MATERIAL_BEFORE.pattern,
            "explicit_material_after": _EXPLICIT_MATERIAL_AFTER.pattern,
        },
        "excluded_prefix_patterns": {
            code: pattern.pattern for code, pattern in _EXCLUDED_PREFIX_PATTERNS.items()
        },
        "item_suffix_patterns": {
            code: pattern.pattern for code, pattern in _ITEM_AFTER.items()
        },
        "uppercase_item_suffix_patterns": {
            code: pattern.pattern
            for code, pattern in _UPPERCASE_ITEM_SUFFIX_PATTERNS.items()
        },
    }


def make_material_expander(names: dict[str, str], rules: dict) -> Callable[[str], str]:
    code_pattern = re.compile(rules["code_pattern"])
    context = {
        name: re.compile(pattern) for name, pattern in rules["context_patterns"].items()
    }
    explicit_codes = set(rules["explicit_material_codes"])
    excluded_prefixes = {
        code: re.compile(pattern)
        for code, pattern in rules["excluded_prefix_patterns"].items()
    }
    item_suffixes = {
        code: re.compile(pattern)
        for code, pattern in rules["item_suffix_patterns"].items()
    }
    uppercase_suffixes = {
        code: re.compile(pattern)
        for code, pattern in rules["uppercase_item_suffix_patterns"].items()
    }

    def expand(question: str) -> str:
        terms = []
        for match in code_pattern.finditer(question):
            code = match["code"].upper()
            name = names.get(code)
            if name is None or name in question or name in terms:
                continue
            before, after = question[: match.start()], question[match.end() :]
            excluded_prefix = excluded_prefixes.get(code)
            if excluded_prefix is not None and excluded_prefix.search(before):
                continue
            item_after = item_suffixes.get(code)
            uppercase_item_after = uppercase_suffixes.get(code)
            if code in explicit_codes:
                matches_context = context["explicit_material_before"].search(
                    before
                ) or context["explicit_material_after"].match(after)
            else:
                matches_context = (
                    context["mark_before"].search(before)
                    or context["component_before"].search(before)
                    or context["mark_after"].match(after)
                )
            if (
                matches_context
                or (item_after and item_after.match(after))
                or (
                    uppercase_item_after
                    and match["code"] == code
                    and uppercase_item_after.match(after)
                )
            ):
                terms.append(name)
        suffix = "".join(f" ({term})" for term in terms)
        return f"{question.rstrip()}{suffix}" if suffix else question

    return expand


@cache
def _default_material_expander() -> Callable[[str], str]:
    return make_material_expander(_MATERIAL_NAMES, material_matching_rules())


def expand_material_codes(question: str) -> str:
    """재질 문맥에서 확인한 약어의 정식 명칭만 검색문 뒤에 추가한다."""
    return _default_material_expander()(question)
