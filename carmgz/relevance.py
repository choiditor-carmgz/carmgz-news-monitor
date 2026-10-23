"""Title evidence, shared by acquisition and analysis; never rewrite source titles."""
import re

AUTOMOTIVE = re.compile(
    r'자동차|현대차|기아|전기차|자율주행|모빌리티|전기버스|타이어|투싼|'
    r'토요타|도요타|벤츠|폴스타|리튬금속전지|테슬라|포르쉐|폭스바겐|'
    r'마세라티|벤틀리|지커|르노|쉐보레|쌍용차|한국타이어|넥센|금호타이어|'
    r'케이카|K카|그레칼레|카이엔|아우디|렉서스|볼보|랜드로버|'
    r'(?<![A-Za-z])(?:BMW|MINI|GM|PBV|EV[369]|iX5)(?![A-Za-z])', re.I)
HUNGER = re.compile(r'기아\s*대책|기아\s*문제|기아\s*퇴치|굶주림|기아\(飢餓\)')


def automotive_terms(title):
    if HUNGER.search(title):
        return []
    return list(dict.fromkeys(m.group(0) for m in AUTOMOTIVE.finditer(title)))
