"""Offline editorial triage from retained title/time/publisher evidence, not fact verification."""
from functools import lru_cache
import hashlib
import json
import math
import re
from difflib import SequenceMatcher

WEIGHTS = dict(impact=35, spread=25, novelty=25, timeliness=15)
VERSION = 'editorial-v1'
COMPANIES = {
    '현대차':r'현대차|현대자동차', '기아':r'기아', '볼보그룹':r'볼보\s*그룹',
    '볼보':r'볼보(?!\s*그룹)', 'GM':r'\bGM\b|제너럴\s*모터스|한국GM',
    '테슬라':r'테슬라', 'BMW':r'\bBMW\b', '벤츠':r'벤츠|메르세데스',
    '토요타':r'토요타|도요타', '혼다':r'혼다', '포드':r'포드', '르노':r'르노',
    '폭스바겐':r'폭스바겐', '스텔란티스':r'스텔란티스', '립모터':r'립모터',
    '삼성SDI':r'삼성SDI', 'LG에너지솔루션':r'LG에너지솔루션|LG엔솔',
    'SK온':r'SK온', '현대모비스':r'현대모비스', '현대글로비스':r'현대글로비스',
    '한국타이어':r'한국타이어', '금호타이어':r'금호타이어', '넥센':r'넥센',
    'BYD':r'\bBYD\b|비야디', '지커':r'지커', '폴스타':r'폴스타',
}
ACTIONS = {
    'policy':r'관세|규제|법안|법률|보조금|제재|인증\s*(?:취소|위조)|KC.*가짜',
    'safety':r'리콜|결함|화재|구동력\s*상실|소비자\s*피해',
    'restructure':r'감원|감축|구조조정|희망퇴직|퇴사|사업\s*철수|턴어라운드',
    'earnings':r'적자|영업이익|영업익|매출|실적|수익성',
    'production':r'공장|투자|생산\s*(?:중단|중지|재개)|양산|공급(?!망)|공급망.*(?:차질|재편|위기)',
    'technology':r'자율주행|전고체|배터리|충전|전지|FSD|로봇|V2X',
    'market':r'판매|수입|점유율|가격전쟁|경쟁\s*구도|계약.*(?:돌파|최다|최고|실적)',
    'launch':r'출시|사전계약|계약\s*개시|신차|신형',
}
MATERIAL = r'확대|축소|추가|변경|철회|폐지|삭감|중단|재개|감원|감축'
# Decision state of a plan/policy/deal. Different states are different news even with identical wording otherwise.
DECISIONS = {
    'confirmed': r'승인|확정|체결|시행|통과|가결|타결|결정(?!\s*(?:유보|보류))',
    'cancelled': r'취소|철회|무산|백지화|불발|부결|부인|결렬|보류|유보',
    'tentative': r'검토|추진|논의|협의|가능성|꺼내|저울질|예정|계획',
}


def decision(title):
    """Most decisive state named in a title: cancelled > confirmed > tentative, or None."""
    for state in ('cancelled', 'confirmed', 'tentative'):
        if re.search(DECISIONS[state], title):
            return state
    return None
CONCRETE = r'시행|확정|계약\s*체결|공급|양산|상용화|도입|출범|생산\s*중단|리콜|감원'
DIRECT = r'관세|규제|법안|리콜|결함|공장|투자|감원|적자|양산|상용화|출시|사전계약|배터리|자율주행|신차|충전|전기차|엔진|구동계'
SPORT = r'골프대회|골프\s*마케팅|LPGA|레이디스|챔피언십|e[ -]?스포츠|넷플릭스|앰버서더|축구|야구|후원|협찬|사회공헌|기부'
MOTORSPORT = r'모터스포츠|\bF1\b|WRC|르망|레이싱|랠리|포뮬러'


def context(title):
    """Analysis-only guard: acquisition and the stored source titles remain unchanged."""
    if re.search(r'소주|맥주|푸드360',title) and not re.search(r'전기차|자율주행|차량|배터리',title):
        return 'irrelevant','음료·식품 문맥의 자동차 이름 동음이의어'
    if re.search(MOTORSPORT,title,re.I):
        return 'relevant','모터스포츠 산업·기술 문맥 (선정 가치는 별도 평가)'
    if re.search(SPORT,title,re.I) and not re.search(DIRECT,title,re.I):
        return 'review','경기·협찬·문화행사 문맥: 자동차 산업의 실질적 변화 근거 부족'
    return None


@lru_cache(maxsize=4096)
def facts(title):
    entities = tuple(k for k,p in COMPANIES.items() if re.search(p,title,re.I))
    actions = tuple(k for k,p in ACTIONS.items() if re.search(p,title,re.I))
    # Age expressions (30대 남성) are not vehicle counts. No currency conversion.
    quantities = []
    for m in re.finditer(r'(\d[\d,.]*(?:\s*(?:조|억|만|천)\s*\d[\d,.]*)*\s*(?:조|억|만|천)?)\s*(대|명|원|달러|%)',title):
        if m[2]=='대' and re.match(r'\s*(?:남성|여성|남자|여자)',title[m.end():]):
            continue
        value=sum(float(n.replace(',',''))*{'만':10000,'천':1000,'억':100000000,'조':1000000000000}.get(power,1)
            for n,power in re.findall(r'(\d[\d,.]*)\s*(조|억|만|천)?',m[1]))
        if math.isfinite(value):
            quantities.append((m[2],value))
    periods = tuple(sorted(set(re.findall(r'([1-4])\s*(?:분기|Q)',title,re.I))))
    models = tuple(sorted(set(x.casefold() for x in re.findall(r'\b(?:[A-Za-z]+[- ]?\d+[A-Za-z]*|FSD|PBV)\b|투싼|카운티|쏘나타|쏘렌토|발리',title,re.I))))
    years=tuple(sorted(set(re.findall(r'(20\d{2})(?:년)?',title))))
    subjects=tuple(sorted(set(re.findall(r'전기차|내연기관|하이브리드|승용차|상용차|수입차|전고체|배터리|로봇|수소차|트럭|버스|레벨\s*[0-5]',title))))
    locations=tuple(sorted(set(re.findall(r'울산|아산|광주|화성|평택|인도|유럽|미국|중국|발리|부산|서울|인천|독일|프랑스',title))))
    words = frozenset(re.findall(r'[가-힣]{2,}|[A-Za-z][A-Za-z0-9]+',title.casefold()))
    return dict(entities=entities,actions=actions,quantities=tuple(sorted(set(quantities))),
                periods=periods,models=models,locations=locations,years=years,subjects=subjects,words=words)


def related_event(left,right):
    """Conservative generic extension; existing event/time/conflict guards run first."""
    from .rss import normalized_title
    a,b = facts(left),facts(right)
    if normalized_title(left)==normalized_title(right):
        return 'exact-title','동일 정규화 제목'
    shared_entities = set(a['entities']) & set(b['entities'])
    shared_actions = set(a['actions']) & set(b['actions'])
    if not shared_entities or not shared_actions:
        return None
    # Same company and reporting quarter is specific earnings evidence; group/automaker differ.
    if 'earnings' in shared_actions and a['periods'] and a['periods']==b['periods']:
        if bool(re.search('적자',left)) != bool(re.search('적자',right)):
            return None
        return 'earnings','동일 기업·분기 실적 제목 근거'
    if 'restructure' in shared_actions:
        staff_a = {v for u,v in a['quantities'] if u=='명'}
        staff_b = {v for u,v in b['quantities'] if u=='명'}
        if staff_a and staff_a==staff_b:
            return 'restructure','동일 기업·인원 규모·구조조정 제목 근거'
    if a['locations'] and b['locations'] and not set(a['locations']) & set(b['locations']):
        return None
    # A shared brand alone, or a shared action alone, never merges events.
    common_models = set(a['models']) & set(b['models'])
    similarity = SequenceMatcher(None,normalized_title(left),normalized_title(right)).ratio()
    distinct = a['words'] & b['words'] - {'출시','공개','발표','자동차','전기차','현대차','기아','올해','최초','신형'}
    if ('production' in shared_actions and set(a['locations']) & set(b['locations']) and
        len(distinct)>=3 and re.search(r'기존|종전|당초',left+' '+right) and re.search(MATERIAL,left+' '+right)):
        return 'explicit-change','동일 기업·지역·생산 사업의 명시적 변경 제목 단서'
    if (common_models and len(distinct)>=3 and similarity>=.45) or (len(distinct)>=4 and similarity>=.72):
        return 'title-evidence','동일 기업·행동·구체 제목 단서 (그룹 전체 검증)'
    return None


GENERIC = frozenset('''출시 공개 발표 개최 진행 추진 강화 확대 기록 돌파 국내 글로벌 올해 최초 신형 이번 관련 위해 통해 대한
    시장 자동차 전기차 현대차 기아 그룹 현대차그룹 코리아 사진 포토 종합 속보 단독 시작 본격 계획 나선다 나서 미래 기술 고객'''.split())
PARTICLE = re.compile(r'(?:으로|에서|에게|까지|부터|이다|은|는|이|가|을|를|에|의|와|과|도|로|만)$')


@lru_cache(maxsize=4096)
def title_terms(title):
    import unicodedata
    text = re.sub(r'\[[^\]]*\]', ' ', unicodedata.normalize('NFKC', title).casefold())
    terms = set()
    for word in re.findall(r'[가-힣]{2,}|[a-z][a-z0-9]+|\d+(?:[.,]\d+)?[가-힣a-z%]*', text):
        if re.fullmatch(r'[가-힣]{3,}', word):
            word = PARTICLE.sub('', word)
        if len(word) >= 2 and word not in GENERIC:
            terms.add(word)
    return frozenset(terms)


@lru_cache(maxsize=8192)
def bigram_overlap(left, right):
    from .rss import normalized_title
    a, b = (normalized_title(x) for x in (left, right))
    a, b = ({x[i:i+2] for i in range(len(x)-1)} for x in (a, b))
    return len(a & b)/len(a | b) if a | b else 0


def close(x, y):
    """Rounded reports of one figure (7400억/7500억, 1만5045대/1만5000대) stay compatible."""
    # Small counts/ordinals (20번째, 11대) are exact facts, not rounded figures.
    return x == y or (max(x, y) >= 100 and abs(x-y) <= .1*max(x, y))


def similar_event(left, right):
    """Generic wording evidence for events no hand-written rule anticipated.

    Requires several shared specific terms (company/model/place/number words beyond
    generic verbs and brand names) AND character overlap; callers apply time/fact vetoes.
    """
    shared = title_terms(left) & title_terms(right)
    overlap = bigram_overlap(left, right)
    # Serial/numbered titles (1번째, 2번째) differ only by numbers; require a common figure.
    numbers = [{float(n.replace(',','')) for n in re.findall(r'\d[\d,]*(?:\.\d+)?',x)} for x in (left,right)]
    if all(numbers) and not any(close(x,y) for x in numbers[0] for y in numbers[1]):
        return None
    if (len(shared) >= 3 and overlap >= .28) or (len(shared) >= 2 and overlap >= .35):
        return 'title-overlap', '구체 단어 복수 일치 + 제목 문자 유사도 (그룹 과반 검증)'
    return None


def material_signature(issue):
    """Adding publishers/repeated titles with the same facts does not invalidate a search."""
    profiles = [facts(a['title']) for a in issue['articles']]
    value = {key:sorted(set(v for p in profiles for v in p[key]))
             for key in ('entities','actions','quantities','periods','models','locations','years','subjects')}
    value['changes'] = sorted(set(m.group(0) for a in issue['articles'] for m in re.finditer(MATERIAL,a['title'])))
    # 승인 -> 취소 must invalidate a cached coverage result even when every other fact is equal.
    value['decisions'] = sorted({d for a in issue['articles'] for d in [decision(a['title'])] if d})
    # Unknown event facts must not cause unrelated singleton titles to share a fingerprint.
    if not value['entities'] and not value['models']:
        from .rss import normalized_title
        value['title'] = normalized_title(issue['label'])
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def score(issue, at):
    from .analysis import timestamp
    from .rss import normalized_title
    rows = [(a,timestamp(a.get('published_at'))) for a in issue['articles']]
    rows = [(a,t) for a,t in rows if t is None or 0 <= (at-t).total_seconds() < 168*3600]
    if not rows:
        issue.update(importance_score=0,importance_reasons=[],selection_reasons=[],score_components={},editorial_eligible=False)
        return
    titles = [a['title'] for a,_ in rows]
    joined = ' '.join(titles)
    profiles = [facts(t) for t in titles]
    actions = set().union(*(set(p['actions']) for p in profiles))
    evidence = []
    rubric = [('policy',30,'정책·관세·규제'),('safety',24,'안전·리콜·소비자 피해'),
              ('restructure',28,'구조조정·감원'),('earnings',23,'실적·손익'),
              ('production',22,'생산·투자·공급'),('technology',15,'핵심 기술'),
              ('market',14,'판매·시장 구조'),('launch',8,'신차·상품 발표')]
    best = max((r for r in rubric if r[0] in actions),key=lambda x:x[1],default=(None,6,'자동차 산업 관련 제목'))
    if best[0]=='restructure' and re.search('퇴사',joined) and not re.search(r'감원|감축|구조조정|희망퇴직|철수',joined):
        best=('restructure',10,'퇴사·보상제도: 조직 변화 규모 미확인')
    impact = best[1]
    evidence.append('제목 단서: '+best[2])
    if re.search(r'생산\s*(?:중단|중지)|공장.*(?:신설|건설|착공)|사업\s*철수',joined):
        impact=max(impact,30)
    if 'technology' in actions and re.search(r'양산|상용화|실제\s*물류|도입|실증',joined):
        impact=max(impact,25)
    if 'market' in actions and re.search(r'점유율|수입.*(?:돌파|급증)|가격전쟁|경쟁\s*구도',joined):
        impact=max(impact,22)
    large = [(u,v) for p in profiles for u,v in p['quantities']
             if (u=='명' and v>=1000) or (u=='대' and v>=10000) or
                (u=='원' and v>=100_000_000_000) or (u=='달러' and v>=100_000_000)]
    if large and actions & {'policy','safety','restructure','earnings','production','market'}:
        impact+=5
        def label(unit,value):
            for scale,name in ((1e12,'조'),(1e8,'억'),(1e4,'만')):
                if value>=scale and unit in ('원','달러','대'):
                    return f'{value/scale:g}{name}{unit}'
            return f'{value:,.0f}{unit}'
        evidence.append('제목상 규모: '+' · '.join(sorted({label(u,v) for u,v in large})[:2])+' (원문 확인 필요)')
    if 'safety' in actions and re.search(r'사망|숨져|인명',joined):
        impact+=3
    # Promotion is allowed as automotive news, but cannot inherit technology significance by name alone.
    if re.search(SPORT,joined,re.I) and not re.search(r'관세|규제|리콜|공장|감원|적자|양산|상용화',joined):
        impact=min(impact,8)
    if re.search(r'세미나|토론회|워크숍|신간|발간|강연|테크톡|창립.*주년|공장.*주년',joined) and not re.search(r'투자.*확정|계약\s*체결|공장.*착공|리콜|규제.*시행',joined):
        impact=min(impact,8)
    impact=min(35,impact)

    pubs = {a['publisher'] for a,_ in rows}
    pairs = [(a,b) for n,a in enumerate(titles) for b in titles[n+1:]]
    similar = sum(SequenceMatcher(None,normalized_title(a),normalized_title(b)).ratio()>=.85 for a,b in pairs)
    ratio=similar/len(pairs) if pairs else 0
    spread=min(25,25*math.log2(1+len(pubs))/math.log2(13))*(1-.5*ratio)

    first=min((t for _,t in rows if t),default=None)
    effective=first
    changed=False
    for a,t in sorted((r for r in rows if r[1]),key=lambda r:r[1]):
        if not re.search(MATERIAL,a['title']) or not re.search(r'기존|종전|당초|에서|대비',a['title']):
            continue
        now_facts=facts(a['title'])
        for old,ot in rows:
            prior=facts(old['title'])
            if ot and (t-ot).total_seconds()>=3600 and now_facts['quantities'] and prior['quantities'] and \
               set(now_facts['quantities']) & set(prior['quantities']) and \
               set(now_facts['quantities'])-set(prior['quantities']) and set(now_facts['actions']) & set(prior['actions']):
                effective=max(effective,t);changed=True
    age=(at-effective).total_seconds()/3600 if effective else None
    # Observable first appearance IN THIS RETAINED SAMPLE; not a claim of world-first reporting.
    novelty=(15*math.exp(-age/72) if age is not None else 0)+(5 if re.search(CONCRETE,joined) else 0)+(5 if changed else 0)
    recent={a['publisher'] for a,t in rows if t and 0 <= (at-t).total_seconds()<10800}
    previous={a['publisher'] for a,t in rows if t and 10800 <= (at-t).total_seconds()<21600}
    acceleration=min(3,max(0,len(recent)-len(previous))) if len(previous)>=2 else 0
    timeliness=(12*math.exp(-age/24) if age is not None else 0)+acceleration
    components={k:round(v,2) for k,v in dict(impact=impact,spread=spread,novelty=novelty,timeliness=timeliness).items()}
    reasons = evidence[:2]+[f'{len(pubs)}개 등록 매체 (자체취재 독립성 미검증)',
        ('비교 표현·기존 및 변경 수치 명시: 원문 확인 필요' if changed else
         f'표본 내 최초 발행 {age:.1f}시간 경과' if age is not None else '발행 시각 미확인: 시의성 추정 안 함')]
    if ratio:
        reasons.append(f'유사 제목 쌍 {ratio:.0%}: 확산 점수 보정 (전재 확정 아님)')
    if acceleration:
        reasons.append(f'최근 3시간 {len(recent)}개 매체 / 직전 3시간 {len(previous)}개 매체')
    issue.update(importance_score=round(sum(components.values()),2),score_components=components,
        importance_reasons=[dict(criterion=label,points=components[key],maximum=WEIGHTS[key])
            for key,label in [('impact','산업 영향·규모'),('spread','등록 매체 확산'),('novelty','표본 신규성·변화 단서'),('timeliness','시의성·증가')]],
        selection_reasons=reasons,ranking_version=VERSION,editorial_eligible=True,
        effective_event_at=effective.isoformat() if effective else None,material_signature=material_signature(issue))
    separate_policy = bool(re.search(r'관세.*(?:인상|인하|부과|시행|면제|변경)|규제.*(?:시행|강화|완화|폐지)|법안.*(?:통과|발의)|보조금.*(?:삭감|폐지)',joined))
    issue['business_context'] = dict(entities=sorted(set(e for p in profiles for e in p['entities'])),
        periods=sorted(set(v for p in profiles for v in p['periods'])),
        financial=(bool(actions & {'restructure','earnings'}) or bool(re.search(r'투자.*(?:축소|감축)',joined))) and not separate_policy)


def rank(issues, limit=10):
    from .analysis import timestamp
    ordered=sorted((i for i in issues if i.get('editorial_eligible',True)),
        key=lambda i:(-i['importance_score'],-i.get('score_components',{}).get('impact',0),i['id']))
    selected=[]
    for issue in ordered:
        c=issue.get('business_context',{})
        duplicate=False
        for prior in selected:
            p=prior.get('business_context',{})
            if not (c.get('financial') and p.get('financial') and set(c['entities']) & set(p['entities'])):
                continue
            if c['periods'] and p['periods'] and c['periods']!=p['periods']:
                continue
            a,b=timestamp(issue.get('first_published_at')),timestamp(prior.get('first_published_at'))
            if a and b and abs((a-b).total_seconds())<=72*3600:
                duplicate=True;break
        if not duplicate:
            selected.append(issue)
        if len(selected)>=limit:
            break
    return selected
