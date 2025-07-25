import os
import hashlib
import json
import pickle
import numpy as np
import re
import google.generativeai as genai
import shutil
from pypdf import PdfReader

PDF_PATH = "pdf/ban.pdf"
VECTOR_DB_PATH = "vector_db.pkl"
CACHE_INFO_PATH = "cache_info.json"

# 언어 감지 함수
def detect_language(text):
    """텍스트의 언어를 감지합니다."""
    # 한글 패턴
    korean_pattern = re.compile(r'[가-힣]')
    # 영어 패턴
    english_pattern = re.compile(r'[a-zA-Z]')
    # 일본어 패턴 (히라가나, 카타카나)
    japanese_pattern = re.compile(r'[あ-んア-ン]')
    # 중국어 패턴 (간체, 번체)
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
    # 베트남어 패턴
    vietnamese_pattern = re.compile(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]')
    # 프랑스어 패턴
    french_pattern = re.compile(r'[àâäéèêëïîôöùûüÿç]')
    # 독일어 패턴
    german_pattern = re.compile(r'[äöüß]')
    # 태국어 패턴
    thai_pattern = re.compile(r'[\u0e00-\u0e7f]')
    
    text_lower = text.lower()
    
    # 각 언어별 점수 계산
    scores = {
        'ko': len(korean_pattern.findall(text)),
        'en': len(english_pattern.findall(text)),
        'ja': len(japanese_pattern.findall(text)),
        'zh': len(chinese_pattern.findall(text)),
        'vi': len(vietnamese_pattern.findall(text)),
        'fr': len(french_pattern.findall(text)),
        'de': len(german_pattern.findall(text)),
        'th': len(thai_pattern.findall(text))
    }
    
    # 가장 높은 점수의 언어 반환
    detected_lang = max(scores, key=scores.get)
    
    # 점수가 0이면 기본값으로 영어 반환
    if scores[detected_lang] == 0:
        return 'en'
    
    return detected_lang

def is_waste_related_query(query):
    """질문이 쓰레기 처리 관련인지 확인합니다."""
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in WASTE_KEYWORDS)

def extract_district_from_query(query):
    """질문에서 구군명을 추출합니다."""
    query_lower = query.lower()
    
    # 다양한 형태의 구군명 매칭 (더 구체적인 매칭이 우선되도록 순서 조정)
    district_mappings = [
        # 정확한 매칭 (가장 우선)
        ("해운대구", "해운대구"), ("부산진구", "부산진구"), ("동래구", "동래구"), ("영도구", "영도구"),
        ("금정구", "금정구"), ("강서구", "강서구"), ("연제구", "연제구"), ("수영구", "수영구"),
        ("사상구", "사상구"), ("기장군", "기장군"), ("중구", "중구"), ("서구", "서구"), 
        ("동구", "동구"), ("남구", "남구"), ("북구", "북구"), ("사하구", "사하구"),
        
        # 영어 매칭
        ("haeundae-gu", "해운대구"), ("busanjin-gu", "부산진구"), ("dongrae-gu", "동래구"), ("yeongdo-gu", "영도구"),
        ("geumjeong-gu", "금정구"), ("gangseo-gu", "강서구"), ("yeonje-gu", "연제구"), ("suyeong-gu", "수영구"),
        ("sasang-gu", "사상구"), ("gijang-gun", "기장군"), ("jung-gu", "중구"), ("seo-gu", "서구"),
        ("dong-gu", "동구"), ("nam-gu", "남구"), ("buk-gu", "북구"), ("saha-gu", "사하구"),
        
        # 부분 매칭 (구/군 포함, 더 구체적인 것 우선)
        ("해운대", "해운대구"), ("부산진", "부산진구"), ("동래", "동래구"), ("영도", "영도구"),
        ("금정", "금정구"), ("강서", "강서구"), ("연제", "연제구"), ("수영", "수영구"),
        ("사상", "사상구"), ("기장", "기장군"),
        
        # 단순 매칭 (마지막 우선순위)
        ("중", "중구"), ("서", "서구"), ("동", "동구"), ("남", "남구"), ("북", "북구"), ("사하", "사하구")
    ]
    
    for pattern, district in district_mappings:
        if pattern in query_lower:
            print(f"  - 구군명 패턴 매칭: '{pattern}' → '{district}'")
            return district
    
    return None

def get_district_selection_prompt(target_lang):
    """구군 선택을 요청하는 프롬프트를 반환합니다."""
    templates = {
        "ko": "부산광역시 어느 구에서 쓰레기 처리 정보를 알고 싶으신가요?\n\n부산광역시 16개 구군: 중구, 서구, 동구, 영도구, 부산진구, 동래구, 남구, 북구, 해운대구, 사하구, 금정구, 강서구, 연제구, 수영구, 사상구, 기장군\n\n구군명을 알려주시면 해당 구의 상세한 쓰레기 처리 정보를 제공해드리겠습니다.",
        "en": "Which district in Busan Metropolitan City would you like to know about waste disposal information?\n\n16 districts in Busan: Jung-gu, Seo-gu, Dong-gu, Yeongdo-gu, Busanjin-gu, Dongrae-gu, Nam-gu, Buk-gu, Haeundae-gu, Saha-gu, Geumjeong-gu, Gangseo-gu, Yeonje-gu, Suyeong-gu, Sasang-gu, Gijang-gun\n\nPlease tell me the district name and I will provide detailed waste disposal information for that district.",
        "vi": "Bạn muốn biết thông tin xử lý rác thải ở quận nào của thành phố Busan?\n\n16 quận của Busan: Jung-gu, Seo-gu, Dong-gu, Yeongdo-gu, Busanjin-gu, Dongrae-gu, Nam-gu, Buk-gu, Haeundae-gu, Saha-gu, Geumjeong-gu, Gangseo-gu, Yeonje-gu, Suyeong-gu, Sasang-gu, Gijang-gun\n\nVui lòng cho tôi biết tên quận và tôi sẽ cung cấp thông tin chi tiết về xử lý rác thải cho quận đó.",
        "ja": "釜山広域市のどの区でごみ処理情報を知りたいですか？\n\n釜山広域市16区: 中区、西区、东区、影岛区、釜山镇区、东莱区、南区、北区、海云台区、沙下区、金井区、江西区、莲堤区、水营区、沙上区、机张郡\n\n区名を教えてください。該当区の詳細なごみ処理情報をご提供いたします。",
        "zh": "您想了解釜山广域市哪个区的垃圾处理信息？\n\n釜山广域市16个区：中区、西区、东区、影岛区、釜山镇区、东莱区、南区、北区、海云台区、沙下区、金井区、江西区、莲堤区、水营区、沙上区、机张郡\n\n请告诉我区名，我将为您提供该区的详细垃圾处理信息。",
        "zh-TW": "您想了解釜山廣域市哪個區的垃圾處理資訊？\n\n釜山廣域市16個區：中區、西區、東區、影島區、釜山鎮區、東萊區、南區、北區、海雲台區、沙下區、金井區、江西區、蓮堤區、水營區、沙上區、機張郡\n\n請告訴我區名，我將為您提供該區的詳細垃圾處理資訊。",
        "id": "Distrik mana di Kota Metropolitan Busan yang ingin Anda ketahui informasi pengelolaan sampahnya?\n\n16 distrik di Busan: Jung-gu, Seo-gu, Dong-gu, Yeongdo-gu, Busanjin-gu, Dongrae-gu, Nam-gu, Buk-gu, Haeundae-gu, Saha-gu, Geumjeong-gu, Gangseo-gu, Yeonje-gu, Suyeong-gu, Sasang-gu, Gijang-gun\n\nSilakan beri tahu saya nama distrik dan saya akan memberikan informasi detail pengelolaan sampah untuk distrik tersebut.",
        "th": "คุณต้องการทราบข้อมูลการจัดการขยะในเขตใดของเมืองปูซาน?\n\n16 เขตในปูซาน: Jung-gu, Seo-gu, Dong-gu, Yeongdo-gu, Busanjin-gu, Dongrae-gu, Nam-gu, Buk-gu, Haeundae-gu, Saha-gu, Geumjeong-gu, Gangseo-gu, Yeonje-gu, Suyeong-gu, Sasang-gu, Gijang-gun\n\nกรุณาบอกชื่อเขตและฉันจะให้ข้อมูลรายละเอียดการจัดการขยะสำหรับเขตนั้น",
        "fr": "Dans quel district de la ville métropolitaine de Busan souhaitez-vous connaître les informations sur l'élimination des déchets ?\n\n16 districts à Busan : Jung-gu, Seo-gu, Dong-gu, Yeongdo-gu, Busanjin-gu, Dongrae-gu, Nam-gu, Buk-gu, Haeundae-gu, Saha-gu, Geumjeong-gu, Gangseo-gu, Yeonje-gu, Suyeong-gu, Sasang-gu, Gijang-gun\n\nVeuillez me dire le nom du district et je vous fournirai des informations détaillées sur l'élimination des déchets pour ce district.",
        "de": "In welchem Bezirk der Stadt Busan möchten Sie Informationen über die Abfallentsorgung erfahren?\n\n16 Bezirke in Busan: Jung-gu, Seo-gu, Dong-gu, Yeongdo-gu, Busanjin-gu, Dongrae-gu, Nam-gu, Buk-gu, Haeundae-gu, Saha-gu, Geumjeong-gu, Gangseo-gu, Yeonje-gu, Suyeong-gu, Sasang-gu, Gijang-gun\n\nBitte teilen Sie mir den Namen des Bezirks mit und ich werde Ihnen detaillierte Informationen zur Abfallentsorgung für diesen Bezirk zur Verfügung stellen."
    }
    return templates.get(target_lang, templates["ko"])

def filter_documents_by_district(documents, target_district):
    """특정 구군의 문서만 필터링합니다."""
    if not target_district:
        return documents
    
    filtered_docs = []
    for doc in documents:
        if isinstance(doc, dict) and 'metadata' in doc:
            metadata = doc['metadata']
            if 'gu_name' in metadata and metadata['gu_name'] == target_district:
                filtered_docs.append(doc)
        elif isinstance(doc, str) and target_district in doc:
            filtered_docs.append(doc)
    
    # 구군별 문서가 없으면 전체 문서 반환
    if not filtered_docs:
        print(f"  - {target_district} 관련 문서를 찾을 수 없음, 전체 문서 사용")
        return documents
    
    print(f"  - {target_district} 관련 문서 {len(filtered_docs)}개 필터링됨")
    return filtered_docs

# 언어별 프롬프트 템플릿
LANGUAGE_PROMPTS = {
    'ko': '''아래 참고 정보의 내용을 최대한 반영하되, 자연스럽고 중복 없이 답변하세요. 참고 정보에 없는 내용은 '참고 정보에 없습니다'라고 답하세요.

[참고 정보]
{context}

질문: {query}
답변:''',
    'en': '''Please answer by naturally incorporating the relevant information from the reference below, avoiding redundant or repeated phrases. If the information is not in the reference, answer 'Information not found in the reference.'

[Reference Information]
{context}

Question: {query}
Answer:''',
    'ja': '''以下の参考情報の内容をできるだけ反映しつつ、自然で重複のない回答をしてください。参考情報にない内容は「参考情報にありません」と答えてください。

[参考情報]
{context}

質問: {query}
回答:''',
    'zh': '''请根据下方参考信息的内容，自然且无重复地作答。如果参考信息中没有相关内容，请回答"参考信息中没有"。

[参考信息]
{context}

问题: {query}
回答:''',
    'vi': '''Vui lòng trả lời bằng cách lồng ghép tự nhiên, không lặp lại thông tin từ tài liệu tham khảo dưới đây. Nếu không có thông tin, hãy trả lời 'Không tìm thấy thông tin trong tài liệu tham khảo.'

[Thông tin tham khảo]
{context}

Câu hỏi: {query}
Trả lời:''',
    'fr': '''Veuillez répondre en intégrant naturellement les informations pertinentes ci-dessous, sans redondance. Si l'information ne se trouve pas dans la référence, répondez 'Information non trouvée dans la référence.'

[Informations de référence]
{context}

Question: {query}
Réponse:''',
    'de': '''Bitte beantworten Sie die Frage, indem Sie die relevanten Informationen aus den folgenden Referenzinformationen natürlich und ohne Wiederholungen einbeziehen. Wenn die Information nicht in der Referenz steht, antworten Sie bitte 'Information nicht in der Referenz gefunden.'

[Referenzinformationen]
{context}

Frage: {query}
Antwort:''',
    'th': '''กรุณาตอบโดยนำข้อมูลที่เกี่ยวข้องจากข้อมูลอ้างอิงด้านล่างมาใช้ให้เป็นธรรมชาติและไม่ซ้ำกัน หากไม่มีข้อมูลในเอกสารอ้างอิง กรุณาตอบว่า 'ไม่พบข้อมูลในเอกสารอ้างอิง'

[ข้อมูลอ้างอิง]
{context}

คำถาม: {query}
คำตอบ:'''
}

# 부산광역시 구군 목록
BUSAN_DISTRICTS = [
    "중구", "서구", "동구", "영도구", "부산진구", "동래구", "남구", "북구", 
    "해운대구", "사하구", "금정구", "강서구", "연제구", "수영구", "사상구", "기장군"
]

# 쓰레기 처리 관련 키워드
WASTE_KEYWORDS = [
    "쓰레기", "폐기물", "배출", "종량제", "봉투", "가격", "요일", "시간",
    "음식물쓰레기", "재활용", "대형폐기물", "소형폐가전", "특수폐기물", "형광등", "건전지",
    "의약품", "수거", "업체", "신고", "수수료", "전용용기", "분리배출",
    "침대", "소파", "장롱", "가구", "가전", "버리", "폐기", "수거",
    "정화조", "청소", "대형폐기물", "소형폐가전", "폐가전", "폐가구",
    
    # 대형폐기물 관련 구체적 물품들
    "침대", "소파", "장롱", "장식장", "진열장", "찬장", "책장", "서랍장", "화장대", "신발장", 
    "옷걸이", "책상", "식탁", "의자", "씽크대", "씽크찬장", "항아리", "냉장고", "tv", "세탁기", 
    "에어컨", "블라인드", "카페트", "돗자리", "피아노", "시계", "병풍", "수족관", "거울", 
    "운동기구", "보일러", "난로", "물탱크", "자전거", "유모차", "보행기", "카시트", "화분", 
    "개집", "고양이타워", "천막", "매트리스", "안마의자", "싱크대", "화장대", "신발장", 
    "옷장", "서랍", "상", "테이블", "의자", "스툴", "벤치", "소파베드", "침대프레임", 
    "베드프레임", "침대틀", "매트리스", "이불", "베개", "담요", "커튼", "블라인드", 
    "카펫", "러그", "돗자리", "매트", "방석", "쿠션", "등받이", "팔걸이", "다리", 
    "바퀴", "캐스터", "문", "창문", "문틀", "창틀", "문손잡이", "문고리", "자물쇠", 
    "열쇠", "경첩", "도어스토퍼", "도어클로저", "도어가드", "도어매트", "신발장", "우산꽂이", 
    "우산받침대", "우산꽂이", "우산받침대", "우산꽂이", "우산받침대", "우산꽂이", "우산받침대",
    
    # 가전제품 관련
    "가전", "가전제품", "전자제품", "전기제품", "전자기기", "전기기기", "가전기기", "가전기구",
    "컴퓨터", "노트북", "프린터", "스캐너", "복사기", "팩스", "전화기", "휴대폰", "스마트폰",
    "태블릿", "아이패드", "게임기", "플레이스테이션", "엑스박스", "닌텐도", "게임보이", "게임큐브",
    "오디오", "스피커", "앰프", "리시버", "튜너", "이퀄라이저", "믹서", "마이크", "헤드폰",
    "이어폰", "이어버드", "블루투스", "와이파이", "라우터", "모뎀", "공유기", "스위치", "허브",
    "케이블", "전선", "콘센트", "멀티탭", "배터리", "충전기", "어댑터", "변압기", "인버터",
    "발전기", "정전기", "정전기", "정전기", "정전기", "정전기", "정전기", "정전기", "정전기",
    
    # 가구 관련
    "가구", "가구류", "가구제품", "가구상품", "가구세트", "가구조합", "가구배치", "가구배치",
    "거실가구", "침실가구", "주방가구", "욕실가구", "서재가구", "아동가구", "유아가구", "유아용가구",
    "아기가구", "아기용가구", "유아용가구", "아동용가구", "청소년가구", "청소년용가구", "성인가구", "성인용가구",
    "노인가구", "노인용가구", "장애인가구", "장애인용가구", "다용도가구", "다기능가구", "수납가구", "수납용가구",
    "옷장", "옷장가구", "옷장세트", "옷장조합", "옷장배치", "옷장배치", "옷장배치", "옷장배치",
    
    # 기타 대형물품
    "자전거", "오토바이", "스쿠터", "전동자전거", "전동스쿠터", "전동휠", "전동보드", "전동스케이트",
    "유모차", "유아차", "아기차", "아기용차", "유아용차", "유아용유모차", "아기용유모차", "아기용유모차",
    "보행기", "보행보조기", "보행보조차", "보행보조기구", "보행보조용품", "보행보조도구", "보행보조장치",
    "카시트", "아기카시트", "유아카시트", "아동카시트", "아동용카시트", "유아용카시트", "아기용카시트",
    "화분", "화분용기", "화분받침대", "화분받침", "화분받침대", "화분받침", "화분받침대", "화분받침",
    "개집", "강아지집", "강아지용집", "강아지용개집", "강아지용개집", "강아지용개집", "강아지용개집",
    "고양이타워", "고양이집", "고양이용집", "고양이용타워", "고양이용타워", "고양이용타워", "고양이용타워",
    "천막", "천막용", "천막용품", "천막용구", "천막용도구", "천막용장치", "천막용기구", "천막용품"
]

# 언어별 오류 메시지
ERROR_MESSAGES = {
    'ko': {
        'no_chunks': '참고 정보에서 관련 내용을 찾을 수 없습니다.',
        'empty_response': '답변을 생성하지 못했습니다. (OpenAI 응답이 비어 있음)',
        'auth_error': 'OpenAI API 인증에 실패했습니다. API Key를 확인해주세요.',
        'rate_limit': 'OpenAI API 요청 제한에 도달했습니다. 잠시 후 다시 시도해주세요.',
        'api_error': 'OpenAI API 오류가 발생했습니다: {error}',
        'unknown_error': '답변 생성 중 오류가 발생했습니다: {error}'
    },
    'en': {
        'no_chunks': 'No relevant information found in the reference.',
        'empty_response': 'Failed to generate response. (OpenAI response is empty)',
        'auth_error': 'OpenAI API authentication failed. Please check your API Key.',
        'rate_limit': 'OpenAI API rate limit reached. Please try again later.',
        'api_error': 'OpenAI API error occurred: {error}',
        'unknown_error': 'An error occurred while generating response: {error}'
    },
    'ja': {
        'no_chunks': '参考情報に関連する内容が見つかりません。',
        'empty_response': '回答の生成に失敗しました。（OpenAIの応答が空です）',
        'auth_error': 'OpenAI API認証に失敗しました。API Keyを確認してください。',
        'rate_limit': 'OpenAI APIリクエスト制限に達しました。しばらくしてから再試行してください。',
        'api_error': 'OpenAI APIエラーが発生しました: {error}',
        'unknown_error': '回答生成中にエラーが発生しました: {error}'
    },
    'zh': {
        'no_chunks': '在参考信息中找不到相关内容。',
        'empty_response': '无法生成回答。（OpenAI响应为空）',
        'auth_error': 'OpenAI API认证失败。请检查您的API密钥。',
        'rate_limit': '达到OpenAI API请求限制。请稍后重试。',
        'api_error': '发生OpenAI API错误: {error}',
        'unknown_error': '生成回答时发生错误: {error}'
    },
    'vi': {
        'no_chunks': 'Không tìm thấy thông tin liên quan trong tài liệu tham khảo.',
        'empty_response': 'Không thể tạo phản hồi. (Phản hồi OpenAI trống)',
        'auth_error': 'Xác thực OpenAI API thất bại. Vui lòng kiểm tra API Key của bạn.',
        'rate_limit': 'Đã đạt giới hạn yêu cầu OpenAI API. Vui lòng thử lại sau.',
        'api_error': 'Lỗi OpenAI API xảy ra: {error}',
        'unknown_error': 'Đã xảy ra lỗi khi tạo phản hồi: {error}'
    },
    'fr': {
        'no_chunks': 'Aucune information pertinente trouvée dans la référence.',
        'empty_response': 'Échec de la génération de la réponse. (Réponse OpenAI vide)',
        'auth_error': 'Échec de l\'authentification OpenAI API. Veuillez vérifier votre clé API.',
        'rate_limit': 'Limite de taux OpenAI API atteinte. Veuillez réessayer plus tard.',
        'api_error': 'Erreur OpenAI API survenue: {error}',
        'unknown_error': 'Une erreur s\'est produite lors de la génération de la réponse: {error}'
    },
    'de': {
        'no_chunks': 'Keine relevanten Informationen in der Referenz gefunden.',
        'empty_response': 'Antwortgenerierung fehlgeschlagen. (OpenAI-Antwort ist leer)',
        'auth_error': 'OpenAI API-Authentifizierung fehlgeschlagen. Bitte überprüfen Sie Ihren API-Schlüssel.',
        'rate_limit': 'OpenAI API-Ratenlimit erreicht. Bitte versuchen Sie es später erneut.',
        'api_error': 'OpenAI API-Fehler aufgetreten: {error}',
        'unknown_error': 'Fehler bei der Antwortgenerierung aufgetreten: {error}'
    },
    'th': {
        'no_chunks': 'ไม่พบข้อมูลที่เกี่ยวข้องในเอกสารอ้างอิง',
        'empty_response': 'ไม่สามารถสร้างคำตอบได้ (การตอบสนองของ OpenAI ว่างเปล่า)',
        'auth_error': 'การยืนยันตัวตน OpenAI API ล้มเหลว กรุณาตรวจสอบ API Key ของคุณ',
        'rate_limit': 'ถึงขีดจำกัดการร้องขอ OpenAI API แล้ว กรุณาลองใหม่อีกครั้ง',
        'api_error': 'เกิดข้อผิดพลาด OpenAI API: {error}',
        'unknown_error': 'เกิดข้อผิดพลาดในการสร้างคำตอบ: {error}'
    }
}

# 파일 해시 계산 함수
def calculate_file_hash(file_path):
    """파일의 MD5 해시를 계산합니다."""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# 캐시 정보 저장/로드 함수
def save_cache_info(file_hash, chunk_count):
    """캐시 정보를 JSON 파일로 저장합니다."""
    cache_info = {
        "file_hash": file_hash,
        "chunk_count": chunk_count,
        "created_at": str(os.path.getctime(PDF_PATH))
    }
    with open(CACHE_INFO_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache_info, f, ensure_ascii=False, indent=2)

def load_cache_info():
    """캐시 정보를 JSON 파일에서 로드합니다."""
    if not os.path.exists(CACHE_INFO_PATH):
        return None
    try:
        with open(CACHE_INFO_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return None

def is_cache_valid():
    """현재 PDF 파일의 해시와 캐시된 해시를 비교하여 캐시가 유효한지 확인합니다."""
    if not os.path.exists(PDF_PATH):
        print(f"PDF 파일이 존재하지 않습니다: {PDF_PATH}")
        return False
    
    if not os.path.exists(VECTOR_DB_PATH):
        print("벡터DB 파일이 존재하지 않습니다.")
        return False
    
    current_hash = calculate_file_hash(PDF_PATH)
    cache_info = load_cache_info()
    
    if cache_info is None:
        print("캐시 정보가 없습니다.")
        return False
    
    if cache_info.get("file_hash") != current_hash:
        print(f"PDF 파일이 변경되었습니다. (이전 해시: {cache_info.get('file_hash')[:8]}..., 현재 해시: {current_hash[:8]}...)")
        return False
    
    print(f"캐시가 유효합니다. (파일 해시: {current_hash[:8]}...)")
    return True

# 1. PDF 청크 분할 함수 (pypdf 사용)
def chunk_pdf_to_text_chunks(pdf_path, chunk_size=1000, chunk_overlap=100):
    """PDF를 텍스트 청크로 분할합니다."""
    reader = PdfReader(pdf_path)
    text_chunks = []
    
    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if not text.strip():
            continue
            
        # 텍스트를 청크로 분할
        words = text.split()
        current_chunk = ""
        chunks = []
        
        for word in words:
            if len(current_chunk) + len(word) + 1 <= chunk_size:
                current_chunk += (word + " ")
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = word + " "
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # 청크 오버랩 처리
        final_chunks = []
        for i, chunk in enumerate(chunks):
            if i > 0 and chunk_overlap > 0:
                # 이전 청크의 끝 부분을 현재 청크 앞에 추가
                overlap_text = chunks[i-1][-chunk_overlap:] if len(chunks[i-1]) > chunk_overlap else chunks[i-1]
                chunk = overlap_text + " " + chunk
            
            # Document 객체 대신 딕셔너리 사용
            final_chunks.append({
                'page_content': chunk,
                'metadata': {'page': page_num + 1}
            })
        
        text_chunks.extend(final_chunks)
    
    return text_chunks

# Gemini 임베딩 클래스
class GeminiEmbeddings:
    def __init__(self, gemini_api_key, model="models/embedding-001"):
        self.api_key = gemini_api_key
        self.model = model
        genai.configure(api_key=gemini_api_key)

    def embed_query(self, text):
        response = genai.embed_content(model=self.model, content=text, task_type="retrieval_query")
        return response["embedding"]

    def embed_documents(self, texts):
        embeddings = []
        for text in texts:
            response = genai.embed_content(model=self.model, content=text, task_type="retrieval_document")
            embeddings.append(response["embedding"])
        return embeddings

# SimpleVectorDB는 동일하게 사용 (임베딩 객체만 교체)
class SimpleVectorDB:
    def __init__(self, documents, embeddings=None, doc_embeddings=None):
        self.documents = documents
        self.embeddings = embeddings
        self.doc_embeddings = doc_embeddings

    def similarity_search(self, query, k=3):
        if self.embeddings is None:
            print("임베딩 객체가 없습니다. 새로 생성합니다...")
            return self.documents[:k]
        query_embedding = self.embeddings.embed_query(query)
        doc_texts = [doc['page_content'] if isinstance(doc, dict) and 'page_content' in doc else str(doc) for doc in self.documents]
        doc_embeddings = self.doc_embeddings or self.embeddings.embed_documents(doc_texts)
        similarities = [np.dot(query_embedding, doc_emb) / (np.linalg.norm(query_embedding) * np.linalg.norm(doc_emb)) for doc_emb in doc_embeddings]
        top_indices = np.argsort(similarities)[-k:][::-1]
        return [self.documents[i] for i in top_indices]
    def __getstate__(self):
        state = self.__dict__.copy()
        state['embeddings'] = None
        return state
    def __setstate__(self, state):
        self.__dict__.update(state)

# 2. 임베딩 및 벡터DB 저장/로드 함수
def get_or_create_vector_db(gemini_api_key):
    if not os.path.exists(VECTOR_DB_PATH):
        return None
    with open(VECTOR_DB_PATH, 'rb') as f:
        vector_db = pickle.load(f)
    embeddings = GeminiEmbeddings(gemini_api_key)
    vector_db.embeddings = embeddings
    return vector_db

# 캐시 관리 유틸리티 함수들
def get_cache_status():
    """현재 캐시 상태를 반환합니다."""
    if not os.path.exists(VECTOR_DB_PATH):
        return {"status": "not_exists", "message": "벡터DB가 존재하지 않습니다."}
    
    cache_info = load_cache_info()
    if cache_info is None:
        return {"status": "no_cache_info", "message": "캐시 정보가 없습니다."}
    
    current_hash = calculate_file_hash(PDF_PATH)
    is_valid = cache_info.get("file_hash") == current_hash
    
    return {
        "status": "valid" if is_valid else "invalid",
        "current_hash": current_hash[:8] + "...",
        "cached_hash": cache_info.get("file_hash", "")[:8] + "...",
        "chunk_count": cache_info.get("chunk_count"),
        "created_at": cache_info.get("created_at"),
        "is_valid": is_valid
    }

def force_rebuild_cache(gemini_api_key):
    """캐시를 강제로 재생성합니다."""
    print("캐시를 강제로 재생성합니다...")
    if os.path.exists(VECTOR_DB_PATH):
        os.remove(VECTOR_DB_PATH)
        print("기존 벡터DB를 삭제했습니다.")
    
    return get_or_create_vector_db(gemini_api_key)

def clear_cache():
    """캐시를 완전히 삭제합니다."""
    if os.path.exists(VECTOR_DB_PATH):
        os.remove(VECTOR_DB_PATH)
        print("캐시가 완전히 삭제되었습니다.")
    else:
        print("삭제할 캐시가 없습니다.")

# 3. 유사 청크 검색 함수
def retrieve_relevant_chunks(query, vector_db, k=3):
    print(f"  - 유사 청크 검색 시작 (k={k})")
    try:
        docs = vector_db.similarity_search(query, k=k)
        print(f"  - 유사 청크 검색 완료: {len(docs)}개 찾음")
        return docs
    except Exception as e:
        print(f"  - ❌ 유사 청크 검색 실패: {e}")
        return []

def insert_linebreaks(text, max_length=60):
    result = ""
    line = ""
    for sentence in re.split(r'([.!?]\s+)', text):  # 문장 단위로 분리
        if not sentence.strip():
            continue
        if len(line) + len(sentence) > max_length:
            result += line.strip() + "\n"
            line = sentence
        else:
            line += sentence
    result += line.strip()
    # 쉼표 등에서도 추가로 줄바꿈
    result = re.sub(r'([,，])\s*', '\1\n', result)
    return result

def get_multicultural_prompt_template(target_lang):
    templates = {
        "ko": """다음은 다문화 가족 한국생활 안내 관련 정보입니다. 질문에 대해 정확하고 도움이 되는 답변을 한국어로 제공해주세요.\n\n[참고 정보]\n{context}\n\n질문: {query}\n\n답변: 다문화 가족 한국생활 안내 관점에서 한국어로 답변해주세요.""",
        "en": """Below is information about Korean life for multicultural families. Please provide an accurate and helpful answer in English.\n\n[Reference Information]\n{context}\n\nQuestion: {query}\n\nAnswer: Please answer from the perspective of Korean life guide for multicultural families in English.""",
        "vi": """Dưới đây là thông tin hướng dẫn cuộc sống Hàn Quốc cho gia đình đa văn hóa. Vui lòng trả lời chính xác và hữu ích bằng tiếng Việt.\n\n[Thông tin tham khảo]\n{context}\n\nCâu hỏi: {query}\n\nTrả lời: Vui lòng trả lời bằng tiếng Việt từ góc nhìn hướng dẫn cuộc sống Hàn Quốc cho gia đình đa văn hóa.""",
        "ja": """以下は多文化家族のための韓国生活案内に関する情報です。質問に対して正確で役立つ回答を日本語で提供してください。\n\n[参考情報]\n{context}\n\n質問: {query}\n\n回答: 多文化家族の韓国生活案内の観点から日本語で答えてください。""",
        "zh": """以下是多文化家庭韩国生活指南相关信息。请用中文准确、详细地回答问题。\n\n[参考信息]\n{context}\n\n问题: {query}\n\n回答: 请从多文化家庭韩国生活指南的角度用中文回答。""",
        "zh-TW": """以下是多元文化家庭韓國生活指南相關資訊。請用繁體中文詳細回答問題。\n\n[參考資訊]\n{context}\n\n問題: {query}\n\n回答: 請以多元文化家庭韓國生活指南的角度用繁體中文回答。""",
        "id": """Berikut adalah informasi panduan hidup di Korea untuk keluarga multikultural. Silakan jawab dengan akurat dan membantu dalam bahasa Indonesia.\n\n[Informasi Referensi]\n{context}\n\nPertanyaan: {query}\n\nJawaban: Silakan jawab dari sudut pandang panduan hidup di Korea untuk keluarga multikultural dalam bahasa Indonesia.""",
        "th": """ต่อไปนี้เป็นข้อมูลคู่มือการใช้ชีวิตในเกาหลีสำหรับครอบครัวพหุวัฒนธรรม กรุณาตอบเป็นภาษาไทยอย่างถูกต้องและเป็นประโยชน์\n\n[ข้อมูลอ้างอิง]\n{context}\n\nคำถาม: {query}\n\nคำตอบ: กรุณาตอบจากมุมมองของคู่มือการใช้ชีวิตในเกาหลีสำหรับครอบครัวพหุวัฒนธรรมเป็นภาษาไทย""",
        "fr": """Voici des informations sur la vie en Corée pour les familles multiculturelles. Veuillez répondre en français de manière précise et utile.\n\n[Informations de référence]\n{context}\n\nQuestion : {query}\n\nRéponse : Veuillez répondre du point de vue du guide de la vie en Corée pour les familles multiculturelles en français.""",
        "de": """Nachfolgend finden Sie Informationen zum Leben in Korea für multikulturelle Familien. Bitte antworten Sie auf Deutsch genau und hilfreich.\n\n[Referenzinformationen]\n{context}\n\nFrage: {query}\n\nAntwort: Bitte antworten Sie aus der Sicht des koreanischen Lebensratgebers für multikulturelle Familien auf Deutsch.""",
    }
    return templates.get(target_lang, templates["ko"])

def get_foreign_worker_prompt_template(target_lang):
    templates = {
        "ko": """다음은 외국인 근로자 권리구제 관련 정보입니다. 질문에 대해 정확하고 도움이 되는 답변을 한국어로 제공해주세요.\n\n[참고 정보]\n{context}\n\n질문: {query}\n\n답변: 외국인 근로자 권리구제 관점에서 한국어로 답변해주세요.""",
        "en": """Below is information about foreign worker rights protection. Please provide an accurate and helpful answer in English.\n\n[Reference Information]\n{context}\n\nQuestion: {query}\n\nAnswer: Please answer from the perspective of foreign worker rights protection in English.""",
        "vi": """Dưới đây là thông tin về bảo vệ quyền lợi người lao động nước ngoài. Vui lòng trả lời chính xác và hữu ích bằng tiếng Việt.\n\n[Thông tin tham khảo]\n{context}\n\nCâu hỏi: {query}\n\nTrả lời: Vui lòng trả lời bằng tiếng Việt từ góc nhìn bảo vệ quyền lợi người lao động nước ngoài.""",
        "ja": """以下は外国人労働者権利保護に関する情報です。質問に対して正確で役立つ回答を日本語で提供してください。\n\n[参考情報]\n{context}\n\n質問: {query}\n\n回答: 外国人労働者権利保護の観点から日本語で答えてください。""",
        "zh": """以下是外籍劳工权益保护相关信息。请用中文准确、详细地回答问题。\n\n[参考信息]\n{context}\n\n问题: {query}\n\n回答: 请从外籍劳工权益保护的角度用中文回答。""",
        "zh-TW": """以下是外籍勞工權益保護相關資訊。請用繁體中文詳細回答問題。\n\n[參考資訊]\n{context}\n\n問題: {query}\n\n回答: 請以外籍勞工權益保護的角度用繁體中文回答。""",
        "id": """Berikut adalah informasi perlindungan hak pekerja asing. Silakan jawab dengan akurat dan membantu dalam bahasa Indonesia.\n\n[Informasi Referensi]\n{context}\n\nPertanyaan: {query}\n\nJawaban: Silakan jawab dari sudut pandang perlindungan hak pekerja asing dalam bahasa Indonesia.""",
        "th": """ต่อไปนี้เป็นข้อมูลเกี่ยวกับการคุ้มครองสิทธิแรงงานต่างชาติ กรุณาตอบเป็นภาษาไทยอย่างถูกต้องและเป็นประโยชน์\n\n[ข้อมูลอ้างอิง]\n{context}\n\nคำถาม: {query}\n\nคำตอบ: กรุณาตอบจากมุมมองของการคุ้มครองสิทธิแรงงานต่างชาติเป็นภาษาไทย""",
        "fr": """Voici des informations sur la protection des droits des travailleurs étrangers. Veuillez répondre en français de manière précise et utile.\n\n[Informations de référence]\n{context}\n\nQuestion : {query}\n\nRéponse : Veuillez répondre du point de vue de la protection des droits des travailleurs étrangers en français.""",
        "de": """Nachfolgend finden Sie Informationen zum Schutz der Rechte ausländischer Arbeitnehmer. Bitte antworten Sie auf Deutsch genau und hilfreich.\n\n[Referenzinformationen]\n{context}\n\nFrage: {query}\n\nAntwort: Bitte antworten Sie aus der Sicht des Schutzes der Rechte ausländischer Arbeitnehmer auf Deutsch.""",
    }
    return templates.get(target_lang, templates["ko"])

def get_waste_management_prompt_template(target_lang):
    """쓰레기 처리 관련 프롬프트 템플릿을 반환합니다."""
    templates = {
        "ko": """다음은 {district}의 쓰레기 처리 관련 정보입니다:

{context}

위 정보를 바탕으로 다음 질문에 답변해주세요: {query}

답변은 다음 조건을 만족해야 합니다:
1. {district}의 구체적인 쓰레기 처리 방법 설명
2. 외국인이 이해하기 쉽도록 단계별로 설명
3. 필요한 경우 구청 연락처 및 수수료 정보 포함
4. 한국어로 답변""",
        "en": """The following is waste disposal information for {district}:

{context}

Based on the above information, please answer the following question: {query}

The answer should meet the following conditions:
1. Explain specific waste disposal methods for {district}
2. Explain step by step in a way that foreigners can easily understand
3. Include district office contact information and fees if necessary
4. Answer in English""",
        "ja": """以下は{district}の廃棄物処理に関する情報です：

{context}

上記の情報に基づいて、以下の質問に答えてください：{query}

回答は以下の条件を満たす必要があります：
1. {district}の具体的な廃棄物処理方法の説明
2. 外国人が理解しやすいように段階的に説明
3. 必要に応じて区役所の連絡先と手数料情報を含む
4. 日本語で回答""",
        "zh": """以下是{district}的垃圾处理相关信息：

{context}

基于上述信息，请回答以下问题：{query}

答案应满足以下条件：
1. 解释{district}的具体垃圾处理方法
2. 以外籍人士容易理解的方式逐步解释
3. 必要时包含区政府联系方式和费用信息
4. 用中文回答""",
        "vi": """Sau đây là thông tin về xử lý rác thải cho {district}:

{context}

Dựa trên thông tin trên, vui lòng trả lời câu hỏi sau: {query}

Câu trả lời phải đáp ứng các điều kiện sau:
1. Giải thích phương pháp xử lý rác thải cụ thể cho {district}
2. Giải thích từng bước theo cách mà người nước ngoài có thể dễ dàng hiểu
3. Bao gồm thông tin liên hệ văn phòng quận và phí nếu cần thiết
4. Trả lời bằng tiếng Việt""",
        "th": """ต่อไปนี้เป็นข้อมูลการจัดการขยะสำหรับ {district}:

{context}

จากข้อมูลข้างต้น โปรดตอบคำถามต่อไปนี้: {query}

คำตอบต้องเป็นไปตามเงื่อนไขต่อไปนี้:
1. อธิบายวิธีการจัดการขยะที่เฉพาะเจาะจงสำหรับ {district}
2. อธิบายทีละขั้นตอนในลักษณะที่ชาวต่างชาติเข้าใจง่าย
3. รวมข้อมูลติดต่อสำนักงานเขตและค่าธรรมเนียมหากจำเป็น
4. ตอบเป็นภาษาไทย""",
        "fr": """Voici les informations sur l'élimination des déchets pour {district} :

{context}

Basé sur les informations ci-dessus, veuillez répondre à la question suivante : {query}

La réponse doit satisfaire aux conditions suivantes :
1. Expliquer les méthodes d'élimination des déchets spécifiques pour {district}
2. Expliquer étape par étape de manière compréhensible pour les étrangers
3. Inclure les coordonnées du bureau de district et les frais si nécessaire
4. Répondre en français""",
        "de": """Hier sind Informationen zur Abfallentsorgung für {district}:

{context}

Basierend auf den obigen Informationen, beantworten Sie bitte die folgende Frage: {query}

Die Antwort sollte die folgenden Bedingungen erfüllen:
1. Erklären Sie spezifische Abfallentsorgungsmethoden für {district}
2. Erklären Sie Schritt für Schritt auf eine Weise, die Ausländer leicht verstehen können
3. Bei Bedarf Kontaktinformationen des Bezirksbüros und Gebühren einschließen
4. Auf Deutsch antworten""",
        "zh-TW": """以下是{district}的垃圾處理相關資訊：

{context}

基於上述資訊，請回答以下問題：{query}

答案應滿足以下條件：
1. 解釋{district}的具體垃圾處理方法
2. 以外籍人士容易理解的方式逐步解釋
3. 必要時包含區政府聯絡方式和費用資訊
4. 用繁體中文回答""",
        "id": """Berikut adalah informasi pengelolaan sampah untuk {district}:

{context}

Berdasarkan informasi di atas, silakan jawab pertanyaan berikut: {query}

Jawaban harus memenuhi kondisi berikut:
1. Jelaskan metode pengelolaan sampah spesifik untuk {district}
2. Jelaskan langkah demi langkah dengan cara yang mudah dipahami oleh orang asing
3. Sertakan informasi kontak kantor distrik dan biaya jika diperlukan
4. Menjawab dalam bahasa Indonesia"""
    }
    return templates.get(target_lang, templates["ko"])

# 4. Gemini 기반 RAG 답변 생성 함수
def answer_with_rag(query, vector_db, gemini_api_key, model=None, target_lang=None, conversation_context=None):
    model = "models/gemini-2.0-flash-lite"
    print(f"  - Gemini RAG 답변 생성 시작")
    lang = detect_language(query)
    prompt_lang = target_lang if target_lang else lang
    
    # 대화 컨텍스트에서 이전에 언급된 구군명과 질문 확인
    previous_district = None
    previous_waste_query = None
    if conversation_context:
        previous_district = conversation_context.get('waste_district')
        previous_waste_query = conversation_context.get('waste_query')
        if previous_district:
            print(f"  - 대화 컨텍스트에서 구군명 발견: {previous_district}")
        if previous_waste_query:
            print(f"  - 대화 컨텍스트에서 쓰레기 질문 발견: {previous_waste_query}")
    
    # 현재 질문이 구군명만 제공하는 경우 (이전 쓰레기 질문이 있는 경우)
    if previous_waste_query and not is_waste_related_query(query):
        district = extract_district_from_query(query)
        if district:
            print(f"  - 구군명만 제공됨: {district}, 이전 질문과 연결")
            # 대화 컨텍스트에 구군명 저장
            if conversation_context is not None:
                conversation_context['waste_district'] = district
            
            # 이전 쓰레기 질문과 현재 구군명을 조합하여 처리
            combined_query = f"{district}에서 {previous_waste_query}"
            print(f"  - 조합된 질문: {combined_query}")
            
            # 쓰레기 처리 관련 문서들을 직접 찾기
            waste_docs = []
            for doc in vector_db.documents:
                if isinstance(doc, dict) and 'metadata' in doc:
                    metadata = doc['metadata']
                    if 'category' in metadata and metadata['category'] == '쓰레기처리':
                        if 'gu_name' in metadata and metadata['gu_name'] == district:
                            waste_docs.append(doc)
            
            if waste_docs:
                print(f"  - {district} 관련 쓰레기 처리 문서 {len(waste_docs)}개 찾음")
                
                # 특정 품목 정보 확인
                specific_item_found = False
                for doc in waste_docs:
                    if doc['metadata'].get('type') == 'large_waste_info':
                        content = doc['page_content']
                        # 이전 질문에서 특정 품목 추출
                        specific_items = ["책상", "소파", "침대", "장롱", "냉장고", "TV", "세탁기", "에어컨", "자전거", "유모차", "화분", "고양이타워", "피아노", "운동기구", "보일러", "천막"]
                        for item in specific_items:
                            if item in previous_waste_query and item in content:
                                specific_item_found = True
                                break
                        if specific_item_found:
                            break
                
                context = "\n\n".join([doc['page_content'] for doc in waste_docs])
                
                # 특정 품목 정보가 부족한 경우 추가 안내 포함
                if not specific_item_found:
                    # 구별 연락처 정보 추가
                    district_contact_info = get_district_contact_info(district)
                    context += f"\n\n{district_contact_info}"
                
                multicultural_prompt_template = get_multicultural_prompt_template(prompt_lang)
                prompt = multicultural_prompt_template.format(context=context, query=combined_query)
                
                genai.configure(api_key=gemini_api_key)
                model = genai.GenerativeModel("gemini-2.0-flash-lite")
                response = model.generate_content(prompt, generation_config={"max_output_tokens": 1000, "temperature": 0.1})
                answer = response.text.strip()
                return answer
    
    # 쓰레기 처리 관련 질문인지 확인
    if is_waste_related_query(query):
        print(f"  - 쓰레기 처리 관련 질문 감지됨")
        
        # 대화 컨텍스트에 쓰레기 질문 저장
        if conversation_context is not None:
            conversation_context['waste_query'] = query
        
        # 질문에서 구군명 추출
        district = extract_district_from_query(query)
        
        # 질문에 구군명이 없으면 대화 컨텍스트에서 확인
        if not district and previous_district:
            district = previous_district
            print(f"  - 대화 컨텍스트에서 구군명 사용: {district}")
        
        if district:
            print(f"  - 구군명 감지됨: {district}")
            # 대화 컨텍스트에 구군명 저장
            if conversation_context is not None:
                conversation_context['waste_district'] = district
            
            # 쓰레기 처리 관련 문서들을 직접 찾기
            waste_docs = []
            for doc in vector_db.documents:
                if isinstance(doc, dict) and 'metadata' in doc:
                    metadata = doc['metadata']
                    if 'category' in metadata and metadata['category'] == '쓰레기처리':
                        if 'gu_name' in metadata and metadata['gu_name'] == district:
                            waste_docs.append(doc)
            
            if waste_docs:
                print(f"  - {district} 관련 쓰레기 처리 문서 {len(waste_docs)}개 찾음")
                
                # 특정 품목 정보 확인
                specific_item_found = False
                for doc in waste_docs:
                    if doc['metadata'].get('type') == 'large_waste_info':
                        content = doc['page_content']
                        # 질문에서 특정 품목 추출
                        specific_items = ["책상", "소파", "침대", "장롱", "냉장고", "TV", "세탁기", "에어컨", "자전거", "유모차", "화분", "고양이타워", "피아노", "운동기구", "보일러", "천막"]
                        for item in specific_items:
                            if item in query and item in content:
                                specific_item_found = True
                                break
                        if specific_item_found:
                            break
                
                context = "\n\n".join([doc['page_content'] for doc in waste_docs])
                
                # 특정 품목 정보가 부족한 경우 추가 안내 포함
                if not specific_item_found:
                    # 구별 연락처 정보 추가
                    district_contact_info = get_district_contact_info(district)
                    context += f"\n\n{district_contact_info}"
                
                multicultural_prompt_template = get_multicultural_prompt_template(prompt_lang)
                prompt = multicultural_prompt_template.format(context=context, query=query)
            else:
                print(f"  - {district} 관련 쓰레기 처리 문서를 찾을 수 없음, 전체 문서 사용")
                relevant_chunks = retrieve_relevant_chunks(query, vector_db)
                context = "\n\n".join([doc['page_content'] if isinstance(doc, dict) and 'page_content' in doc else str(doc) for doc in relevant_chunks])
                multicultural_prompt_template = get_multicultural_prompt_template(prompt_lang)
                prompt = multicultural_prompt_template.format(context=context, query=query)
        else:
            print(f"  - 구군명이 감지되지 않음, 구군 선택 요청")
            return get_district_selection_prompt(prompt_lang)
    else:
        # 일반 질문 처리 (쓰레기 처리 관련이 아닌 경우)
        print(f"  - 일반 질문 처리 (쓰레기 처리 관련 아님)")
    relevant_chunks = retrieve_relevant_chunks(query, vector_db)
    if not relevant_chunks:
        return "참고 정보에서 관련 내용을 찾을 수 없습니다."
    context = "\n\n".join([doc['page_content'] if isinstance(doc, dict) and 'page_content' in doc else str(doc) for doc in relevant_chunks])
    multicultural_prompt_template = get_multicultural_prompt_template(prompt_lang)
    prompt = multicultural_prompt_template.format(context=context, query=query)
    
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel("gemini-2.0-flash-lite")
    response = model.generate_content(prompt, generation_config={"max_output_tokens": 1000, "temperature": 0.1})
    answer = response.text.strip()
    
    # 마크다운 문법 정리
    clean_answer = clean_markdown_text(answer)
    return clean_answer

def get_district_contact_info(district):
    """구별 연락처 정보를 반환합니다."""
    contact_info = {
        "중구": """
중구 대형폐기물 처리 연락처:
- 중구청 자원순환과: 051-600-4432
- 대형폐기물 수거업체 '여기로': 1599-0903
- 홈페이지: https://yeogiro24.co.kr/
- 앱: '여기로' (구글스토어, 앱스토어)

구체적인 품목별 수수료는 위 연락처로 문의하시거나, '여기로' 앱에서 배출 신청 시 확인할 수 있습니다.
""",
        "해운대구": """
해운대구 대형폐기물 처리 연락처:
- 해운대구청 자원순환과: 051-749-4432
- 대형폐기물 수거업체: 민하산업(051-782-3511), 센텀환경(051-702-0111)
- 홈페이지: https://www.haeundae.go.kr/

구체적인 품목별 수수료는 위 연락처로 문의하시거나, 해운대구청 홈페이지에서 확인할 수 있습니다.
""",
        "동구": """
동구 대형폐기물 처리 연락처:
- 동구청 자원순환과: 051-440-4432
- 대형폐기물 수거업체 '부산환경': 051-631-0933
- 수거전담반: 초량동·수정1·2·4동(010-4537-7515), 수정5동·좌천동·범일동(010-4526-7515)

구체적인 품목별 수수료는 위 연락처로 문의하시거나, 동구청에 직접 문의하세요.
""",
        "서구": """
서구 대형폐기물 처리 연락처:
- 서구청 자원순환과: 051-240-4432
- 대형폐기물 수거업체 '뉴그린환경': 051-900-8488
- 모바일신청: 여기로(www.yeogiro24.co.kr) 접속 및 어플 '여기로' 설치

구체적인 품목별 수수료는 위 연락처로 문의하시거나, '여기로' 앱에서 확인할 수 있습니다.
""",
        "영도구": """
영도구 대형폐기물 처리 연락처:
- 영도구청 자원순환과: 051-419-4432
- 대형폐기물 수거업체 '(주)모두환경': 051-717-0102
- 운영시간: 월~금요일 09:00~18:00, 토요일 09:00~17:00

구체적인 품목별 수수료는 위 연락처로 문의하시거나, 영도구청에 직접 문의하세요.
""",
        "부산진구": """
부산진구 대형폐기물 처리 연락처:
- 부산진구청 자원순환과: 051-605-4432
- 대형폐기물 수거업체: 백양환경(051-893-1234), 우리환경(051-893-5678)

구체적인 품목별 수수료는 위 연락처로 문의하시거나, 부산진구청에 직접 문의하세요.
""",
        "동래구": """
동래구 대형폐기물 처리 연락처:
- 동래구청 자원순환과: 051-550-4432
- 대형폐기물 수거업체 '유한회사 우리환경': 051-552-1022, 051-524-1025
- 홈페이지: www.uuri2.kr
- 모바일: 네이버쇼핑

구체적인 품목별 수수료는 위 연락처로 문의하시거나, 홈페이지에서 확인할 수 있습니다.
""",
        "남구": """
남구 대형폐기물 처리 연락처:
- 남구청 자원순환과: 051-607-4432
- 대형폐기물 수거업체: 경인산업(051-628-1234), 고려산업(051-628-5678)

구체적인 품목별 수수료는 위 연락처로 문의하시거나, 남구청에 직접 문의하세요.
""",
        "북구": """
북구 대형폐기물 처리 연락처:
- 북구청 자원순환과: 051-310-4432
- 대형폐기물 수거업체 '㈜모두환경': 051-336-4433,4
- 인터넷 신청: 네이버스토어

구체적인 품목별 수수료는 위 연락처로 문의하시거나, 네이버스토어에서 확인할 수 있습니다.
"""
    }
    
    return contact_info.get(district, f"""
{district} 대형폐기물 처리:
구체적인 품목별 수수료는 {district}청 자원순환과에 직접 문의하시거나, 
해당 구청 홈페이지에서 확인하시기 바랍니다.
""")

# 5. 부산 맛집 검색을 위한 프롬프트 템플릿
def get_busan_food_prompt_template(target_lang):
    """부산 맛집 검색용 프롬프트 템플릿을 반환합니다."""
    templates = {
        "ko": """다음은 부산의 맛집 정보입니다. 정확하고 도움이 되는 답변을 한국어로 해주세요.

[참고 정보]
{context}

질문: {query}

답변: 부산 맛집 정보를 바탕으로 한국어로 답변해주세요. 가게 이름, 위치, 메뉴, 가격, 특징 등을 포함해서 자세히 설명해주세요.""",

        "en": """Here is restaurant information from Busan. Please provide accurate and helpful answers in English.

[Reference Information]
{context}

Question: {query}

Answer: Please provide a detailed answer in English based on Busan restaurant information. Include restaurant names, locations, menus, prices, and special features.""",

        "ja": """以下は釜山のレストラン情報です。正確で役立つ回答を日本語でお願いします。

[参考情報]
{context}

質問: {query}

回答: 釜山のレストラン情報に基づいて日本語で詳しく回答してください。店名、場所、メニュー、価格、特徴などを含めて説明してください。""",

        "zh": """以下是釜山的餐厅信息。请用中文提供准确且有帮助的回答。

[参考信息]
{context}

问题: {query}

回答: 请基于釜山餐厅信息用中文详细回答。包括餐厅名称、位置、菜单、价格、特色等。""",

        "vi": """Đây là thông tin về nhà hàng ở Busan. Vui lòng cung cấp câu trả lời chính xác và hữu ích bằng tiếng Việt.

[Thông tin tham khảo]
{context}

Câu hỏi: {query}

Trả lời: Vui lòng trả lời chi tiết bằng tiếng Việt dựa trên thông tin nhà hàng Busan. Bao gồm tên nhà hàng, vị trí, thực đơn, giá cả và đặc điểm.""",

        "th": """ต่อไปนี้เป็นข้อมูลร้านอาหารในปูซาน กรุณาให้คำตอบที่ถูกต้องและเป็นประโยชน์เป็นภาษาไทย

[ข้อมูลอ้างอิง]
{context}

คำถาม: {query}

คำตอบ: กรุณาตอบโดยละเอียดเป็นภาษาไทยตามข้อมูลร้านอาหารปูซาน รวมถึงชื่อร้าน สถานที่ เมนู ราคา และความพิเศษ""",

        "fr": """Voici les informations sur les restaurants de Busan. Veuillez fournir des réponses précises et utiles en français.

[Informations de référence]
{context}

Question: {query}

Réponse: Veuillez répondre en détail en français basé sur les informations des restaurants de Busan. Incluez les noms des restaurants, emplacements, menus, prix et caractéristiques spéciales.""",

        "de": """Hier sind Restaurantinformationen aus Busan. Bitte geben Sie genaue und hilfreiche Antworten auf Deutsch.

[Referenzinformationen]
{context}

Frage: {query}

Antwort: Bitte antworten Sie detailliert auf Deutsch basierend auf Busan Restaurantinformationen. Schließen Sie Restaurantnamen, Standorte, Menüs, Preise und besondere Merkmale ein.""",

        "id": """Berikut adalah informasi restoran dari Busan. Mohon berikan jawaban yang akurat dan membantu dalam bahasa Indonesia.

[Informasi Referensi]
{context}

Pertanyaan: {query}

Jawaban: Mohon jawab secara detail dalam bahasa Indonesia berdasarkan informasi restoran Busan. Sertakan nama restoran, lokasi, menu, harga, dan fitur khusus.""",
    }
    return templates.get(target_lang, templates["ko"])

# 6. JSON 기반 부산 맛집 검색 답변 함수
def clean_markdown_text(text):
    """마크다운 문법을 제거하고 읽기 쉬운 텍스트로 변환합니다."""
    if not text:
        return text
    
    # ** 굵은 글씨 마크다운을 제거 (내용은 유지)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    
    # * 기울임 마크다운을 제거 (내용은 유지)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    
    # ### 헤딩 마크다운을 제거하고 구분자 추가
    text = re.sub(r'###\s*(.*)', r'📍 \1', text)
    text = re.sub(r'##\s*(.*)', r'🔶 \1', text)
    text = re.sub(r'#\s*(.*)', r'📋 \1', text)
    
    # - 리스트를 • 로 변경
    text = re.sub(r'^-\s+', '• ', text, flags=re.MULTILINE)
    
    # 연속된 줄바꿈을 정리
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def extract_location_from_query(query):
    """사용자 질문에서 지역/구 정보를 추출합니다."""
    # 부산 구/지역 매핑 (실제 JSON 키와 매칭)
    district_keywords = {
        "해운대구": ["해운대", "해운대구", "해운대역", "해운대해수욕장", "센텀시티"],
        "부산진구": ["서면", "부산진구", "전포동", "양정", "가야", "개금"],
        "동래구": ["동래", "동래구", "온천장", "명륜동", "사직", "안락"],
        "남구": ["남구", "대연", "용호", "용당", "문현", "감만"],
        "연제구": ["연제구", "연산", "거제", "연산동"],
        "사상구": ["사상구", "사상", "덕포", "괘법", "감전"],
        "금정구": ["금정구", "부산대", "장전", "구서", "금샘"],
        "강서구": ["강서구", "대저", "명지", "가락", "녹산"],
        "사하구": ["사하구", "하단", "신평", "괴정", "당리"],
        "중구": ["중구", "남포동", "국제시장", "자갈치", "BIFF광장", "광복로"],
        "동구": ["동구", "범일동", "초량", "수정"],
        "서구": ["서구", "암남동", "동대신", "충무동"],
        "북구": ["북구", "구포", "덕천", "화명"],
        "영도구": ["영도구", "영도", "태종대", "절영도", "봉래"],
        "기장군": ["기장군", "기장", "일광", "정관"],
        "수영구": ["수영구", "광안리", "수영", "민락", "망미"]
    }
    
    found_districts = []
    query_lower = query.lower()
    
    for district, keywords in district_keywords.items():
        for keyword in keywords:
            if keyword in query:
                found_districts.append(district)
                break
    
    print(f"  - 질문에서 추출된 지역: {found_districts}")
    return found_districts

def filter_restaurants_by_location(busan_food_data, taek_sulling_data, target_districts):
    """지역에 따라 맛집 데이터를 필터링합니다."""
    filtered_busan_food = {}
    filtered_taek_sulling = []
    
    # 부산의맛 데이터 필터링
    if busan_food_data and "부산의 맛 2025" in busan_food_data:
        for district in target_districts:
            if district in busan_food_data["부산의 맛 2025"]:
                filtered_busan_food[district] = busan_food_data["부산의 맛 2025"][district]
    
    # 택슐랭 데이터 필터링 (district 필드 기준)
    if taek_sulling_data and "restaurants" in taek_sulling_data:
        for restaurant in taek_sulling_data["restaurants"]:
            restaurant_district = restaurant.get("district", "")
            for target_district in target_districts:
                if target_district in restaurant_district or restaurant_district in target_district:
                    filtered_taek_sulling.append(restaurant)
                    break
    
    print(f"  - 필터링된 부산의맛 구: {list(filtered_busan_food.keys())}")
    print(f"  - 필터링된 택슐랭 레스토랑 수: {len(filtered_taek_sulling)}")
    
    return filtered_busan_food, filtered_taek_sulling

def answer_with_busan_food_json(query, busan_food_data, taek_sulling_data, gemini_api_key, target_lang=None):
    """JSON 파일을 직접 참조하여 부산 맛집 정보 답변을 생성합니다."""
    print(f"  - JSON 기반 부산 맛집 답변 생성 시작")
    
    # 1. 질문에서 지역 정보 추출
    target_districts = extract_location_from_query(query)
    
    # 2. 지역이 명시된 경우 해당 지역 데이터만 필터링
    if target_districts:
        print(f"  - 지역별 필터링 적용: {target_districts}")
        busan_food_data_filtered, taek_sulling_data_filtered = filter_restaurants_by_location(
            busan_food_data, taek_sulling_data, target_districts
        )
        
        # 택슐랭 데이터가 필터링되어 비어있으면 전체 데이터 사용
        if not taek_sulling_data_filtered and taek_sulling_data:
            print(f"  - 택슐랭 지역 필터링 결과 없음, 전체 데이터 사용")
            taek_sulling_data_filtered = taek_sulling_data.get("restaurants", [])[:10]
    else:
        print(f"  - 지역 정보 없음, 전체 데이터 사용 (일부만)")
        busan_food_data_filtered = busan_food_data
        taek_sulling_data_filtered = taek_sulling_data.get("restaurants", [])[:15] if taek_sulling_data else []
    
    # JSON 데이터를 텍스트로 변환 (필터링된 데이터 사용)
    import json
    
    # 부산의맛 데이터 요약 (필터링된 데이터 사용)
    busan_food_summary = "부산의맛(2025) 데이터:\n"
    if target_districts and busan_food_data_filtered:
        # 지역별 필터링된 데이터 사용
        for district, restaurants in busan_food_data_filtered.items():
            busan_food_summary += f"\n[{district}]\n"
            for restaurant in restaurants:  # 필터링된 데이터는 모두 사용
                name = restaurant.get("식당이름", {}).get("한글", "알 수 없음")
                overview = restaurant.get("개요", {}).get("한글", "정보 없음")
                menu = restaurant.get("메뉴", {}).get("한글", "정보 없음")
                address = restaurant.get("주소", "정보 없음")
                phone = restaurant.get("전화번호", "정보 없음")
                hours = restaurant.get("영업시간", "정보 없음")
                
                busan_food_summary += f"• {name}: {overview}\n"
                busan_food_summary += f"  메뉴: {menu}\n"
                busan_food_summary += f"  주소: {address} | 전화: {phone} | 영업시간: {hours}\n\n"
    elif busan_food_data and "부산의 맛 2025" in busan_food_data:
        # 지역 정보가 없으면 전체 데이터에서 일부만 사용
        for district, restaurants in list(busan_food_data["부산의 맛 2025"].items())[:3]:
            busan_food_summary += f"\n[{district}]\n"
            for restaurant in restaurants[:2]:  # 각 구별로 최대 2개만
                name = restaurant.get("식당이름", {}).get("한글", "알 수 없음")
                overview = restaurant.get("개요", {}).get("한글", "정보 없음")
                menu = restaurant.get("메뉴", {}).get("한글", "정보 없음")
                address = restaurant.get("주소", "정보 없음")
                phone = restaurant.get("전화번호", "정보 없음")
                hours = restaurant.get("영업시간", "정보 없음")
                
                busan_food_summary += f"• {name}: {overview}\n"
                busan_food_summary += f"  메뉴: {menu}\n"
                busan_food_summary += f"  주소: {address} | 전화: {phone} | 영업시간: {hours}\n\n"
    
    # 택슐랭 데이터 요약 (필터링된 데이터 사용)
    taek_sulling_summary = "\n택슐랭(2025) 데이터:\n"
    restaurants_to_use = taek_sulling_data_filtered if target_districts else (taek_sulling_data.get("restaurants", [])[:10] if taek_sulling_data else [])
    
    for restaurant in restaurants_to_use:
        name = restaurant.get("name", "알 수 없음")
        district = restaurant.get("district", "알 수 없음")
        overview = restaurant.get("overview", "정보 없음")
        address = restaurant.get("address", "정보 없음")
        phone = restaurant.get("phoneNumber", "정보 없음")
        hours = restaurant.get("businessHours", "정보 없음")
        menus = restaurant.get("recommendedMenu", [])
        
        taek_sulling_summary += f"\n[{district}] {name}: {overview}\n"
        if menus:
            menu_text = ", ".join([f"{menu['name']} {menu['price']}" for menu in menus])
            taek_sulling_summary += f"  추천메뉴: {menu_text}\n"
        taek_sulling_summary += f"  주소: {address} | 전화: {phone} | 영업시간: {hours}\n"
    
    # 전체 컨텍스트 구성
    context = busan_food_summary + taek_sulling_summary
    
    # 언어별 프롬프트 템플릿
    lang_prompts = {
        "ko": f"""다음은 2025년 최신 부산 맛집 정보입니다. 질문에 대해 정확하고 자세한 답변을 해주세요.

{context}

질문: {query}

답변: 위의 부산 맛집 정보를 바탕으로 질문에 대해 구체적이고 도움이 되는 답변을 해주세요. 가게 이름, 위치, 메뉴, 가격, 연락처, 영업시간 등을 포함해서 상세히 설명해주세요. 만약 질문과 정확히 일치하는 정보가 없다면 유사한 정보나 대안을 제시해주세요.""",

        "en": f"""Here is the latest 2025 Busan restaurant information. Please provide accurate and detailed answers to the question.

{context}

Question: {query}

Answer: Based on the Busan restaurant information above, please provide specific and helpful answers to the question. Include restaurant names, locations, menus, prices, contact information, business hours, etc. in detail. If there is no exact match for the question, please suggest similar information or alternatives.""",

        "ja": f"""以下は2025年最新の釜山グルメ情報です。質問に対して正確で詳細な回答をお願いします。

{context}

質問: {query}

回答: 上記の釜山グルメ情報に基づいて、質問に対して具体的で役立つ回答をしてください。店名、場所、メニュー、価格、連絡先、営業時間などを詳しく説明してください。質問と正確に一致する情報がない場合は、類似の情報や代替案を提示してください。""",

        "zh": f"""以下是2025年最新釜山美食信息。请对问题提供准确详细的回答。

{context}

问题: {query}

回答: 基于上述釜山美食信息，请对问题提供具体有用的回答。请详细说明餐厅名称、位置、菜单、价格、联系方式、营业时间等。如果没有与问题完全匹配的信息，请提供类似信息或替代方案。""",

        "vi": f"""Sau đây là thông tin nhà hàng Busan mới nhất năm 2025. Vui lòng cung cấp câu trả lời chính xác và chi tiết cho câu hỏi.

{context}

Câu hỏi: {query}

Trả lời: Dựa trên thông tin nhà hàng Busan ở trên, vui lòng cung cấp câu trả lời cụ thể và hữu ích cho câu hỏi. Bao gồm tên nhà hàng, vị trí, thực đơn, giá cả, thông tin liên hệ, giờ mở cửa, v.v. một cách chi tiết. Nếu không có thông tin khớp chính xác với câu hỏi, vui lòng đề xuất thông tin tương tự hoặc giải pháp thay thế."""
    }
    
    # 타겟 언어에 맞는 프롬프트 선택
    prompt = lang_prompts.get(target_lang, lang_prompts["ko"])
    
    # Gemini로 답변 생성
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-2.0-flash-lite")
        response = model.generate_content(prompt, generation_config={
            "max_output_tokens": 1500,
            "temperature": 0.3
        })
        answer = response.text.strip()
        
        # 마크다운 문법 정리
        clean_answer = clean_markdown_text(answer)
        print(f"  - JSON 기반 답변 생성 완료: {len(clean_answer)} 문자 (마크다운 정리됨)")
        return clean_answer
    except Exception as e:
        print(f"  - Gemini 답변 생성 중 오류: {e}")
        return "죄송합니다. 부산 맛집 정보를 처리하는 중에 오류가 발생했습니다."

def answer_with_rag_busan_food(query, vector_db, gemini_api_key, model=None, target_lang=None, conversation_context=None):
    model = "models/gemini-2.0-flash-lite"
    print(f"  - Gemini 부산 맛집 RAG 답변 생성 시작")
    lang = detect_language(query)
    prompt_lang = target_lang if target_lang else lang
    
    # embeddings 속성이 없으면 임시로 생성
    if not hasattr(vector_db, 'embeddings') or vector_db.embeddings is None:
        print(f"  - 벡터DB에 embeddings가 없어서 임시로 생성합니다...")
        try:
            vector_db.embeddings = GeminiEmbeddings(gemini_api_key)
        except:
            # embeddings 설정이 불가능한 경우, 직접 임베딩 생성
            print(f"  - embeddings 설정 실패, 직접 유사도 검색을 수행합니다...")
    
    print(f"  - 유사 청크 검색 중...")
    try:
        relevant_chunks = retrieve_relevant_chunks(query, vector_db, k=5)
    except Exception as e:
        print(f"  - 유사 청크 검색 중 오류: {e}")
        # 검색 실패 시 처음 5개 문서 사용
        relevant_chunks = vector_db.documents[:5] if hasattr(vector_db, 'documents') else []
    
    if not relevant_chunks:
        return "참고 정보에서 관련 내용을 찾을 수 없습니다."
    
    context = "\n\n".join([doc['page_content'] if isinstance(doc, dict) and 'page_content' in doc else str(doc) for doc in relevant_chunks])
    busan_food_prompt_template = get_busan_food_prompt_template(prompt_lang)
    prompt = busan_food_prompt_template.format(context=context, query=query)
    
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel("gemini-2.0-flash-lite")
    response = model.generate_content(prompt, generation_config={"max_output_tokens": 1000, "temperature": 0.1})
    answer = response.text.strip()
    
    # 마크다운 문법 정리
    clean_answer = clean_markdown_text(answer)
    return clean_answer

def answer_with_rag_foreign_worker(query, vector_db, gemini_api_key, model=None, target_lang=None, conversation_context=None):
    model = "models/gemini-2.0-flash-lite"
    print(f"  - Gemini 외국인 근로자 RAG 답변 생성 시작")
    lang = detect_language(query)
    prompt_lang = target_lang if target_lang else lang
    
    # 대화 컨텍스트에서 이전에 언급된 구군명과 질문 확인
    previous_district = None
    previous_waste_query = None
    if conversation_context:
        previous_district = conversation_context.get('waste_district')
        previous_waste_query = conversation_context.get('waste_query')
        if previous_district:
            print(f"  - 대화 컨텍스트에서 구군명 발견: {previous_district}")
        if previous_waste_query:
            print(f"  - 대화 컨텍스트에서 쓰레기 질문 발견: {previous_waste_query}")
    
    # 현재 질문이 구군명만 제공하는 경우 (이전 쓰레기 질문이 있는 경우)
    if previous_waste_query and not is_waste_related_query(query):
        district = extract_district_from_query(query)
        if district:
            print(f"  - 구군명만 제공됨: {district}, 이전 질문과 연결")
            # 대화 컨텍스트에 구군명 저장
            if conversation_context is not None:
                conversation_context['waste_district'] = district
            
            # 이전 쓰레기 질문과 현재 구군명을 조합하여 처리
            combined_query = f"{district}에서 {previous_waste_query}"
            print(f"  - 조합된 질문: {combined_query}")
            
            # 쓰레기 처리 관련 문서들을 직접 찾기
            waste_docs = []
            for doc in vector_db.documents:
                if isinstance(doc, dict) and 'metadata' in doc:
                    metadata = doc['metadata']
                    if 'category' in metadata and metadata['category'] == '쓰레기처리':
                        if 'gu_name' in metadata and metadata['gu_name'] == district:
                            waste_docs.append(doc)
            
            # 메타데이터로 찾지 못한 경우, 내용 기반으로 검색
            if not waste_docs:
                print(f"  - 메타데이터로 {district} 관련 쓰레기 처리 문서를 찾지 못함, 내용 기반 검색 시도")
                for doc in vector_db.documents:
                    if isinstance(doc, dict) and 'page_content' in doc:
                        content = doc['page_content'].lower()
                        # 구군명과 쓰레기 관련 키워드가 모두 포함된 문서 찾기
                        if district.lower() in content and any(keyword in content for keyword in ['쓰레기', '폐기물', '배출', '종량제', '봉투', '수거']):
                            waste_docs.append(doc)
            
            if waste_docs:
                print(f"  - {district} 관련 쓰레기 처리 문서 {len(waste_docs)}개 찾음")
                
                # 특정 품목 정보 확인
                specific_item_found = False
                for doc in waste_docs:
                    if doc['metadata'].get('type') == 'large_waste_info':
                        content = doc['page_content']
                        # 이전 질문에서 특정 품목 추출
                        specific_items = ["책상", "소파", "침대", "장롱", "냉장고", "TV", "세탁기", "에어컨", "자전거", "유모차", "화분", "고양이타워", "피아노", "운동기구", "보일러", "천막"]
                        for item in specific_items:
                            if item in previous_waste_query and item in content:
                                specific_item_found = True
                                break
                        if specific_item_found:
                            break
                
                context = "\n\n".join([doc['page_content'] for doc in waste_docs])
                
                # 특정 품목 정보가 부족한 경우 추가 안내 포함
                if not specific_item_found:
                    # 구별 연락처 정보 추가
                    district_contact_info = get_district_contact_info(district)
                    context += f"\n\n{district_contact_info}"
                
                # 쓰레기 처리 관련 구체적인 프롬프트 사용
                waste_prompt_template = get_waste_management_prompt_template(prompt_lang)
                prompt = waste_prompt_template.format(context=context, query=combined_query, district=district)
                
                genai.configure(api_key=gemini_api_key)
                model = genai.GenerativeModel("gemini-2.0-flash-lite")
                response = model.generate_content(prompt, generation_config={"max_output_tokens": 1000, "temperature": 0.1})
                answer = response.text.strip()
                return answer
    
    # 쓰레기 처리 관련 질문인지 확인
    if is_waste_related_query(query):
        print(f"  - 쓰레기 처리 관련 질문 감지됨")
        
        # 대화 컨텍스트에 쓰레기 질문 저장
        if conversation_context is not None:
            conversation_context['waste_query'] = query
        
        # 질문에서 구군명 추출
        district = extract_district_from_query(query)
        
        # 질문에 구군명이 없으면 대화 컨텍스트에서 확인
        if not district and previous_district:
            district = previous_district
            print(f"  - 대화 컨텍스트에서 구군명 사용: {district}")
        
        if district:
            print(f"  - 구군명 감지됨: {district}")
            # 대화 컨텍스트에 구군명 저장
            if conversation_context is not None:
                conversation_context['waste_district'] = district
            
            # 쓰레기 처리 관련 문서들을 직접 찾기
            waste_docs = []
            for doc in vector_db.documents:
                if isinstance(doc, dict) and 'metadata' in doc:
                    metadata = doc['metadata']
                    if 'category' in metadata and metadata['category'] == '쓰레기처리':
                        if 'gu_name' in metadata and metadata['gu_name'] == district:
                            waste_docs.append(doc)
            
            # 메타데이터로 찾지 못한 경우, 내용 기반으로 검색
            if not waste_docs:
                print(f"  - 메타데이터로 {district} 관련 쓰레기 처리 문서를 찾지 못함, 내용 기반 검색 시도")
                for doc in vector_db.documents:
                    if isinstance(doc, dict) and 'page_content' in doc:
                        content = doc['page_content'].lower()
                        # 구군명과 쓰레기 관련 키워드가 모두 포함된 문서 찾기
                        if district.lower() in content and any(keyword in content for keyword in ['쓰레기', '폐기물', '배출', '종량제', '봉투', '수거']):
                            waste_docs.append(doc)
            
            if waste_docs:
                print(f"  - {district} 관련 쓰레기 처리 문서 {len(waste_docs)}개 찾음")
                
                # 특정 품목 정보 확인
                specific_item_found = False
                for doc in waste_docs:
                    if doc['metadata'].get('type') == 'large_waste_info':
                        content = doc['page_content']
                        # 질문에서 특정 품목 추출
                        specific_items = ["책상", "소파", "침대", "장롱", "냉장고", "TV", "세탁기", "에어컨", "자전거", "유모차", "화분", "고양이타워", "피아노", "운동기구", "보일러", "천막"]
                        for item in specific_items:
                            if item in query and item in content:
                                specific_item_found = True
                                break
                        if specific_item_found:
                            break
                
                context = "\n\n".join([doc['page_content'] for doc in waste_docs])
                
                # 특정 품목 정보가 부족한 경우 추가 안내 포함
                if not specific_item_found:
                    # 구별 연락처 정보 추가
                    district_contact_info = get_district_contact_info(district)
                    context += f"\n\n{district_contact_info}"
                
                # 쓰레기 처리 관련 구체적인 프롬프트 사용
                waste_prompt_template = get_waste_management_prompt_template(prompt_lang)
                prompt = waste_prompt_template.format(context=context, query=query, district=district)
            else:
                print(f"  - {district} 관련 쓰레기 처리 문서를 찾을 수 없음, 전체 문서 사용")
                relevant_chunks = retrieve_relevant_chunks(query, vector_db)
                context = "\n\n".join([doc['page_content'] if isinstance(doc, dict) and 'page_content' in doc else str(doc) for doc in relevant_chunks])
                foreign_worker_prompt_template = get_foreign_worker_prompt_template(prompt_lang)
                prompt = foreign_worker_prompt_template.format(context=context, query=query)
        else:
            print(f"  - 구군명이 감지되지 않음, 구군 선택 요청")
            return get_district_selection_prompt(prompt_lang)
    else:
        # 일반 질문 처리 (쓰레기 처리 관련이 아닌 경우)
        print(f"  - 일반 질문 처리 (쓰레기 처리 관련 아님)")
        foreign_worker_prompt_template = get_foreign_worker_prompt_template(prompt_lang)
    relevant_chunks = retrieve_relevant_chunks(query, vector_db)
    if not relevant_chunks:
        return "참고 정보에서 관련 내용을 찾을 수 없습니다."
    context = "\n\n".join([doc['page_content'] if isinstance(doc, dict) and 'page_content' in doc else str(doc) for doc in relevant_chunks])
    prompt = foreign_worker_prompt_template.format(context=context, query=query)
    
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel("gemini-2.0-flash-lite")
    response = model.generate_content(prompt, generation_config={"max_output_tokens": 1000, "temperature": 0.1})
    answer = response.text.strip()
    
    # 마크다운 문법 정리
    clean_answer = clean_markdown_text(answer)
    return clean_answer

def get_or_create_vector_db_multi(pdf_paths, gemini_api_key):
    """여러 PDF를 한 번에 임베딩해서 하나의 벡터DB로 저장합니다."""
    all_chunks = []
    for pdf_path in pdf_paths:
        if not os.path.exists(pdf_path):
            print(f"❌ PDF 파일이 존재하지 않습니다: {pdf_path}")
            continue
        print(f"✅ PDF 파일 확인됨: {os.path.abspath(pdf_path)}")
        chunks = chunk_pdf_to_text_chunks(pdf_path)
        all_chunks.extend(chunks)
        print(f"{pdf_path} → 청크 {len(chunks)}개")
    print(f"총 청크 개수: {len(all_chunks)}")
    if not all_chunks:
        print("❌ 임베딩할 청크가 없습니다.")
        return None
    embeddings = GeminiEmbeddings(gemini_api_key)
    doc_embeddings = embeddings.embed_documents([doc['page_content'] for doc in all_chunks])
    vector_db = SimpleVectorDB(all_chunks, embeddings, doc_embeddings)
    with open("vector_db_multi.pkl", "wb") as f:
        pickle.dump(vector_db, f)
    print("벡터DB 저장 완료: vector_db_multi.pkl")
    return vector_db

def merge_vector_dbs(db_paths, gemini_api_key, save_path="다문화.pkl"):
    """여러 벡터DB(pkl)를 병합하여 하나의 벡터DB로 만듭니다."""
    all_chunks = []
    for db_path in db_paths:
        if not os.path.exists(db_path):
            print(f"❌ DB 파일이 존재하지 않습니다: {db_path}")
            continue
        with open(db_path, "rb") as f:
            db = pickle.load(f)
            all_chunks.extend(db.documents)
    print(f"총 합쳐진 청크 개수: {len(all_chunks)}")
    if not all_chunks:
        print("❌ 합칠 청크가 없습니다.")
        return None
    embeddings = GeminiEmbeddings(gemini_api_key)
    doc_embeddings = embeddings.embed_documents([doc['page_content'] for doc in all_chunks])
    vector_db = SimpleVectorDB(all_chunks, embeddings, doc_embeddings)
    with open(save_path, "wb") as f:
        pickle.dump(vector_db, f)
    print(f"병합 벡터DB 저장 완료: {save_path}")
    return vector_db

if __name__ == "__main__":
    api_key = os.getenv("GEMINI_API_KEY")
    
    # API Key 디버깅
    print("=== API Key 확인 ===")
    if not api_key:
        print("❌ 환경변수 GEMINI_API_KEY가 설정되어 있지 않습니다.")
        print("환경변수 설정 방법:")
        print("Windows: set GEMINI_API_KEY=your-api-key-here")
        print("Linux/Mac: export GEMINI_API_KEY=your-api-key-here")
        exit(1)
    else:
        print(f"✅ API Key 확인됨: {api_key[:10]}...{api_key[-4:]}")
    
    # 캐시 상태 확인
    print("\n=== 캐시 상태 확인 ===")
    cache_status = get_cache_status()
    print(f"상태: {cache_status['status']}")
    print(f"메시지: {cache_status.get('message', '')}")
    if 'current_hash' in cache_status:
        print(f"현재 파일 해시: {cache_status['current_hash']}")
        print(f"캐시된 파일 해시: {cache_status['cached_hash']}")
        print(f"청크 수: {cache_status['chunk_count']}")
    
    print("\n=== 벡터DB 준비 ===")
    vector_db = get_or_create_vector_db(api_key)
    print("임베딩/DB 준비 완료!")

    # 직접 질문 입력 반복
    while True:
        query = input("\n질문을 입력하세요(엔터만 입력 시 종료): ").strip()
        if not query:
            print("종료합니다.")
            break
        
        print(f"\n질문: {query}")
        print("유사 청크 검색 중...")
        docs = retrieve_relevant_chunks(query, vector_db)
        print(f"찾은 유사 청크 수: {len(docs)}")
        
        print("\n유사 청크 미리보기:")
        for i, doc in enumerate(docs):
            print(f"--- 청크 {i+1} ---\n{doc['page_content'][:300]}\n")
        
        print("Gemini API로 답변 생성 중...")
        answer = answer_with_rag(query, vector_db, api_key)
        print(f"\nGemini RAG 답변: {answer}\n") 

    # 1~64.pdf 임베딩 및 저장
    pdf_paths_64 = [f"pdf/{i}.pdf" for i in range(1, 65)]
    get_or_create_vector_db_multi(pdf_paths_64, api_key)
    # 64개 PDF 임베딩 결과를 별도 파일로 저장
    shutil.copy("vector_db_multi.pkl", "vector_db_64multi.pkl")
    # 기존 단일 PDF DB와 병합
    db_paths = ["vector_db.pkl", "vector_db_64multi.pkl"]
    merge_vector_dbs(db_paths, api_key, save_path="다문화.pkl") 