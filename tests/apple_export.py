"""测试用：造一个小的苹果健康导出包（中文系统：导出.zip 里是 apple_health_export/导出.xml）。"""

import zipfile
from datetime import date, timedelta


def export_xml(end: date, days: int = 10) -> str:
    """每天一段睡眠、一次心率变异性（SDNN）、一小时的步数。"""
    rows = []
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        prev = d - timedelta(days=1)
        rows.append(
            f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Apple Watch" startDate="{prev} 23:20:00 +0800" endDate="{d} 06:{40 + i % 10}:00 +0800" value="HKCategoryValueSleepAnalysisAsleepCore"/>'
        )
        rows.append(
            f'<Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" sourceName="Apple Watch" unit="ms" startDate="{d} 07:00:00 +0800" endDate="{d} 07:01:00 +0800" value="{48 + i}"/>'
        )
        rows.append(
            f'<Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" startDate="{d} 09:00:00 +0800" endDate="{d} 10:00:00 +0800" value="{6000 + 300 * i}"/>'
        )
    body = "\n ".join(rows)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!ELEMENT HealthData (ExportDate,Me,(Record|Correlation|Workout)*)>
]>
<HealthData locale="zh_CN">
 <ExportDate value="{end} 08:00:00 +0800"/>
 <Me HKCharacteristicTypeIdentifierDateOfBirth="1995-03-01" HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"/>
 {body}
</HealthData>
'''


def write_zip(
    path: str, end: date, days: int = 10, member: str = "apple_health_export/导出.xml"
) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, export_xml(end, days))
        zf.writestr("apple_health_export/导出_cda.xml", "<ClinicalDocument/>")
