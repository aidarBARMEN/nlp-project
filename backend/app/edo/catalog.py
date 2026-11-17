"""Справочники электронного документооборота (ЭДО): роли, категории, типы документов.

Номенклатура и сроки хранения — демонстрационные значения для учебного проекта;
перед внедрением их сверяют с утверждённой номенклатурой дел университета.
"""

from __future__ import annotations

ROLES: dict[str, dict] = {
    "rector": {"name": "Ректор", "unit": "Ректорат"},
    "registrar": {"name": "Офис Регистратора", "unit": "Офис Регистратора"},
    "admissions": {"name": "Приёмная комиссия", "unit": "Приёмная комиссия"},
    "dean": {"name": "Деканат", "unit": "Деканат школы"},
    "medical": {"name": "Медпункт", "unit": "Медицинский пункт"},
    "practice": {"name": "Отдел практики", "unit": "Отдел практики и карьеры"},
    "hr": {"name": "Отдел кадров", "unit": "Департамент по работе с персоналом"},
    "accounting": {"name": "Бухгалтерия", "unit": "Финансовый департамент"},
    "archive": {"name": "Архив", "unit": "Архив университета"},
}

# Уровни доступа роли к категории: full — метаданные и файл, meta — только карточка без файла
# и примечаний, отсутствие ключа — категория скрыта. create — роль регистрирует документы.
CATEGORIES: dict[str, dict] = {
    "personal_file": {
        "name": "Личные дела студентов", "prefix": "ЛД", "confidentiality": "personal",
        "description": "Документы, которые формируют личное дело обучающегося с момента зачисления до выпуска.",
        "access": {"registrar": "full", "dean": "full", "rector": "full", "archive": "meta"},
        "create": ["registrar", "dean"],
    },
    "admissions": {
        "name": "Приём абитуриентов", "prefix": "ПК", "confidentiality": "personal",
        "description": "Заявления, сертификаты ЕНТ, свидетельства о гранте, протоколы приёмной комиссии.",
        "access": {"admissions": "full", "registrar": "full", "rector": "full", "archive": "meta"},
        "create": ["admissions"],
    },
    "academic": {
        "name": "Учебный процесс", "prefix": "УП", "confidentiality": "internal",
        "description": "Ведомости, рабочие учебные планы, справки с места учёбы, апелляции.",
        "access": {"registrar": "full", "dean": "full", "rector": "full", "archive": "meta"},
        "create": ["registrar", "dean"],
    },
    "practice": {
        "name": "Практика и стажировки", "prefix": "ПР", "confidentiality": "internal",
        "description": "Договоры с базами практики, направления, дневники и отчёты по практике.",
        "access": {"practice": "full", "dean": "full", "rector": "full", "archive": "meta"},
        "create": ["practice", "dean"],
    },
    "medical": {
        "name": "Медицинская документация", "prefix": "МЕД", "confidentiality": "medical",
        "description": "Справки 086-У, прививочные паспорта, профосмотры, справки о нетрудоспособности. "
                       "Содержимое доступно только медпункту.",
        "access": {"medical": "full", "rector": "meta", "dean": "meta", "registrar": "meta"},
        "create": ["medical"],
    },
    "business_trips": {
        "name": "Командировки", "prefix": "КМ", "confidentiality": "internal",
        "description": "Служебные записки, приказы о командировке, авансовые отчёты и отчёты о поездке.",
        "access": {"hr": "full", "accounting": "full", "rector": "full", "archive": "meta"},
        "create": ["hr", "accounting"],
    },
    "hr": {
        "name": "Кадровые документы", "prefix": "ОК", "confidentiality": "personal",
        "description": "Трудовые договоры, приказы по личному составу, заявления сотрудников.",
        "access": {"hr": "full", "rector": "full", "archive": "meta"},
        "create": ["hr"],
    },
    "orders": {
        "name": "Приказы и распоряжения", "prefix": "ПРК", "confidentiality": "internal",
        "description": "Приказы ректора и распоряжения по основной деятельности.",
        "access": {r: "full" for r in ROLES},
        "create": ["rector", "registrar", "hr"],
    },
    "finance": {
        "name": "Договоры и оплата", "prefix": "ФИН", "confidentiality": "internal",
        "description": "Квитанции об оплате обучения, решения о скидках и льготах.",
        "access": {"accounting": "full", "registrar": "full", "rector": "full", "archive": "meta"},
        "create": ["accounting"],
    },
}

# code: (название, категория, срок хранения в годах, маршрут согласования по ролям)
DOC_TYPES: dict[str, tuple[str, str, int, list[str]]] = {
    # личное дело
    "application_enroll": ("Заявление о зачислении", "personal_file", 75, []),
    "id_copy": ("Копия удостоверения личности", "personal_file", 75, []),
    "education_doc": ("Аттестат / диплом об образовании", "personal_file", 75, ["registrar"]),
    "photo": ("Фотографии 3×4", "personal_file", 75, []),
    "study_contract": ("Договор на обучение", "personal_file", 75, ["accounting", "registrar"]),
    "enroll_order": ("Выписка из приказа о зачислении", "personal_file", 75, []),
    "transcript": ("Транскрипт", "personal_file", 75, ["registrar"]),
    "academic_leave": ("Заявление на академический отпуск", "personal_file", 75, ["dean", "registrar", "rector"]),
    "transfer": ("Заявление о переводе / восстановлении", "personal_file", 75, ["dean", "registrar"]),
    # приём
    "applicant_form": ("Заявление абитуриента", "admissions", 5, ["admissions"]),
    "ent_certificate": ("Сертификат ЕНТ", "admissions", 5, []),
    "grant_certificate": ("Свидетельство о присуждении гранта", "admissions", 75, ["admissions"]),
    "admission_protocol": ("Протокол заседания приёмной комиссии", "admissions", 75, ["admissions", "rector"]),
    # учебный процесс
    "grade_sheet": ("Экзаменационная ведомость", "academic", 50, ["dean", "registrar"]),
    "curriculum": ("Рабочий учебный план (РУП)", "academic", 10, ["dean", "registrar", "rector"]),
    "study_reference": ("Справка с места учёбы", "academic", 3, ["registrar"]),
    "appeal": ("Апелляция", "academic", 5, ["dean", "registrar"]),
    # практика
    "practice_contract": ("Договор с базой практики", "practice", 5, ["practice", "dean"]),
    "practice_referral": ("Направление на практику", "practice", 5, ["practice"]),
    "practice_diary": ("Дневник практики", "practice", 5, ["dean"]),
    "practice_report": ("Отчёт по практике", "practice", 5, ["dean"]),
    # медицина
    "med_086": ("Медицинская справка 086-У", "medical", 25, ["medical"]),
    "vaccination": ("Прививочный паспорт (063/у)", "medical", 25, []),
    "sick_leave": ("Справка о временной нетрудоспособности", "medical", 5, ["medical", "dean"]),
    "med_checkup": ("Профосмотр / флюорография", "medical", 5, ["medical"]),
    # командировки
    "trip_memo": ("Служебная записка на командировку", "business_trips", 5, ["hr", "accounting", "rector"]),
    "trip_order": ("Приказ о командировке", "business_trips", 5, ["rector"]),
    "advance_report": ("Авансовый отчёт", "business_trips", 5, ["accounting"]),
    "trip_report": ("Отчёт о командировке", "business_trips", 5, ["hr"]),
    # кадры
    "employment_contract": ("Трудовой договор", "hr", 75, ["hr", "rector"]),
    "hr_order": ("Приказ по личному составу", "hr", 75, ["hr", "rector"]),
    "vacation_request": ("Заявление на отпуск", "hr", 5, ["hr"]),
    # приказы
    "rector_order": ("Приказ ректора по основной деятельности", "orders", 99, ["rector"]),
    "instruction": ("Распоряжение", "orders", 5, ["rector"]),
    # финансы
    "payment_receipt": ("Квитанция об оплате обучения", "finance", 5, ["accounting"]),
    "discount_decision": ("Решение о скидке / льготе", "finance", 5, ["accounting", "rector"]),
}

# Что должно быть в личном деле студента (проверка комплектности)
PERSONAL_FILE_CHECKLIST = [
    "application_enroll", "id_copy", "education_doc", "photo",
    "study_contract", "enroll_order", "med_086",
]

STATUSES = {
    "on_approval": "На согласовании",
    "approved": "Утверждён",
    "rejected": "Отклонён",
    "archived": "В архиве",
}

PERSON_KINDS = {"student": "Студент", "applicant": "Абитуриент", "employee": "Сотрудник"}

# Чьи карточки видит роль (принцип минимально необходимого доступа)
PERSON_ACCESS = {
    "rector": ["student", "applicant", "employee"],
    "registrar": ["student", "applicant"],
    "admissions": ["applicant"],
    "dean": ["student"],
    "medical": ["student", "applicant", "employee"],
    "practice": ["student"],
    "hr": ["employee"],
    "accounting": ["student", "employee"],
    "archive": ["student", "applicant", "employee"],
}

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".jpg", ".jpeg", ".png"}
MAX_FILE_MB = 20


def access(role: str, category: str) -> str | None:
    return CATEGORIES[category]["access"].get(role)


def readable_categories(role: str) -> list[str]:
    return [c for c in CATEGORIES if access(role, c)]


def creatable_types(role: str) -> list[str]:
    return [t for t, (_n, cat, _r, _route) in DOC_TYPES.items() if role in CATEGORIES[cat]["create"]]
