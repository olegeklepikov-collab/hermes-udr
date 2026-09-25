"""Progressive access to reviewed research methods; never a universal gate chain."""
from __future__ import annotations
import importlib
from pathlib import Path

METHODS = {'decomposition': {'module': 'decomposition',
                   'function': 'assess_decomposition',
                   'schema': 'DECOMPOSITION_ASSESS_SCHEMA',
                   'schema_module': 'decomposition',
                   'purpose': 'Проверить декомпозицию по заданию и уровню исследования.',
                   'limitations': 'Проверяет atomic/verifiable, основание листа, зависимости/циклы '
                                  'и перекрытия; это валидация уже предложенной декомпозиции, не '
                                  'применение 5 Whys, GQM, DSM или иных методов из перечня.',
                   'kind': 'supplied_evidence_assessor'},
 'construct_operationalization': {'module': 'decomposition',
                                  'function': 'operationalize_construct',
                                  'schema': 'CONSTRUCT_OPERATIONALIZE_SCHEMA',
                                  'schema_module': 'decomposition',
                                  'purpose': 'Операционализировать определённое понятие для '
                                             'измерения.',
                                  'limitations': 'Требует ровно одно принятое определение, '
                                                 'показатель/меру/единицу, proxy model, validity '
                                                 'refs, failures/confounders и запретные выводы; '
                                                 'наличие полей не удостоверяет эмпирическую '
                                                 'валидность.',
                                  'kind': 'supplied_evidence_assessor'},
 'source_family_coverage': {'module': 'source_families',
                            'function': 'assess_search_coverage',
                            'schema': 'SEARCH_COVERAGE_ASSESS_SCHEMA',
                            'schema_module': 'source_families',
                            'purpose': 'Проверить волны поиска, ячейки и сохранённые записи.',
                            'limitations': 'Сверяет предоставленные волны, происхождение и '
                                           'плотность; не выполняет поиск и не удостоверяет '
                                           'полноту неизвестной вселенной.',
                            'kind': 'supplied_evidence_assessor'},
 'query_ast_compile': {'module': 'search_workflow',
                       'function': 'compile_query_ast',
                       'schema': 'QUERY_AST_COMPILE_SCHEMA',
                       'schema_module': 'search_workflow',
                       'purpose': 'Преобразовать структурированный запрос для заданного '
                                  'компилятора.',
                       'limitations': 'Действительно переводит query AST в объявленный синтаксис; '
                                      'не выполняет запрос и не подтверждает recall.',
                       'kind': 'computation_or_record_build'},
 'search_strategy': {'module': 'search_workflow',
                     'function': 'assess_search_strategy',
                     'schema': 'SEARCH_STRATEGY_ASSESS_SCHEMA',
                     'schema_module': 'search_workflow',
                     'purpose': 'Проверить версию поисковой стратегии и область материала.',
                     'limitations': 'Компилирует или проверяет предоставленную стратегию/среду; не '
                                    'запускает внешний поиск и не доказывает полноту охвата.',
                     'kind': 'supplied_evidence_assessor'},
 'source_selection': {'module': 'sources',
                      'function': 'select_source',
                      'schema': 'SOURCE_SELECT_SCHEMA',
                      'schema_module': 'sources',
                      'purpose': 'Оценить источник-кандидат по требованию и показателям качества.',
                      'limitations': 'Решает роль кандидата по требованию, качеству и доступности; '
                                     'ссылки/флаги поступают извне, полное чтение источника не '
                                     'выполняется.',
                      'kind': 'supplied_evidence_assessor'},
 'source_pool_audit': {'module': 'source_families',
                       'function': 'audit_source_pool',
                       'schema': 'SOURCE_POOL_AUDIT_SCHEMA',
                       'schema_module': 'source_families',
                       'purpose': 'Проверить плотность пула источников и заменяющие семейства.',
                       'limitations': 'Проверяет происхождение, класс и плотность пула, сохраняет '
                                      'монокультуру/замену; не открывает новую семью источников '
                                      'сам.',
                       'kind': 'supplied_evidence_assessor'},
 'independent_support': {'module': 'decisions',
                         'function': 'assess_independent_support',
                         'schema': 'INDEPENDENT_SUPPORT_ASSESS_SCHEMA',
                         'schema_module': 'decisions',
                         'purpose': 'Проверить независимость происхождения опоры тезиса.',
                         'limitations': 'Схлопывает опоры общего происхождения и учитывает '
                                        'одноисточниковое исключение; независимость ограничена '
                                        'достоверностью поданных origin refs.',
                         'kind': 'supplied_evidence_assessor'},
 'claim_challenge': {'module': 'claims',
                     'function': 'evaluate_challenge',
                     'schema': 'CHALLENGE_EVALUATE_SCHEMA',
                     'schema_module': 'claims',
                     'purpose': 'Оценить оспаривание тезиса с учётом доказательной области.',
                     'limitations': 'Оценивает готовый claim и его evidence profile/альтернативы; '
                                    'не порождает автоматически rival hypotheses или '
                                    'контрфактическое повторное исследование.',
                     'kind': 'supplied_evidence_assessor'},
 'business_design': {'module': 'business',
                     'function': 'assess_business_design',
                     'schema': 'BUSINESS_DESIGN_ASSESS_SCHEMA',
                     'schema_module': 'business',
                     'purpose': 'Проверить схему делового исследования и классы доказательств.',
                     'limitations': 'Разводит external signals, internal metrics и causal effects, '
                                    'выбирает методы по входным флагам; не доказывает причинность '
                                    'и не считает экономический эффект.',
                     'kind': 'supplied_evidence_assessor'},
 'business_controls': {'module': 'business_controls',
                       'function': 'assess_business_control',
                       'schema': 'BUSINESS_CONTROL_ASSESS_SCHEMA',
                       'schema_module': 'business_controls',
                       'purpose': 'Проверить типизированный контроль делового исследования.',
                       'limitations': '12 режимов, включая survey, causal, projection, commercial: '
                                      'проверяет рамку/смещение отбора, идентификационные '
                                      'предпосылки и диагностики, различает сценарий и прогноз, '
                                      'запрещает повышение рекламного заявления до измеренного без '
                                      'независимой записи. Опрос/эксперимент/экономическую модель '
                                      'не исполняет.',
                       'kind': 'supplied_evidence_assessor'},
 'academic_protocol': {'module': 'academic',
                       'function': 'assess_academic_protocol',
                       'schema': 'ACADEMIC_PROTOCOL_ASSESS_SCHEMA',
                       'schema_module': 'academic',
                       'purpose': 'Проверить научный протокол и идентичности объектов.',
                       'limitations': 'Проверяет заявленный протокол либо допустимость '
                                      'объединения; не осуществляет поиск или полный научный '
                                      'обзор.',
                       'kind': 'supplied_evidence_assessor'},
 'extraction_review': {'module': 'advanced_academic',
                       'function': 'assess_extraction',
                       'schema': 'EXTRACTION_ASSESS_SCHEMA',
                       'schema_module': 'advanced_academic',
                       'purpose': 'Проверить извлечённые поля по схеме и кодировочной книге.',
                       'limitations': 'Сверяет schema/codebook, два маршрута извлечения, конфликт '
                                      'и adjudication с локатором; не извлекает данные из PDF '
                                      'сама.',
                       'kind': 'supplied_evidence_assessor'},
 'synthesis_comparability': {'module': 'advanced_academic',
                             'function': 'assess_academic_synthesis_gate',
                             'schema': 'ACADEMIC_SYNTHESIS_GATE_SCHEMA',
                             'schema_module': 'advanced_academic',
                             'purpose': 'Проверить допуск научных результатов к синтезу.',
                             'limitations': 'Сопоставляет estimand и обязательные sensitivity '
                                            'receipts, блокирует несовместимое объединение; не '
                                            'запускает метаанализ.',
                             'kind': 'supplied_evidence_assessor'},
 'computation_replay': {'module': 'advanced_academic',
                        'function': 'assess_computation_replay',
                        'schema': 'COMPUTATION_REPLAY_ASSESS_SCHEMA',
                        'schema_module': 'advanced_academic',
                        'purpose': 'Проверить воспроизводимость сохранённого вычисления.',
                        'limitations': 'Сравнивает поданные outputs с допуском и хеши '
                                       'кода/входов/среды, учитывает флаг независимости; не '
                                       'исполняет код повторно.',
                        'kind': 'supplied_evidence_assessor'},
 'fixed_effect_compute': {'module': 'advanced_academic',
                          'function': 'compute_fixed_effect_estimate',
                          'schema': 'FIXED_EFFECT_COMPUTE_SCHEMA',
                          'schema_module': 'advanced_academic',
                          'purpose': 'Рассчитать заданную сводку фиксированного эффекта из '
                                     'записей.',
                          'limitations': 'Действительно считает inverse-variance fixed-effect '
                                         'estimate и интервал по поданным estimate/SE; не '
                                         'проверяет исходные исследования или допустимость '
                                         'pooling.',
                          'kind': 'computation_or_record_build'},
 'numeric_reproduction_assess': {'module': 'numeric_reproduction',
                                 'function': 'assess_numeric_reproduction',
                                 'schema': 'NUMERIC_REPRODUCTION_SCHEMA',
                                 'schema_module': 'numeric_reproduction',
                                 'purpose': 'Проверить расчёт, поддерживающий числовой тезис.',
                                 'limitations': 'Сверяет переданную численную запись с расчётом; '
                                                'происхождение исходных чисел проверяется '
                                                'отдельно.',
                                 'kind': 'supplied_evidence_assessor'}}

SPECIALISTS = {'research_search_ledger_assess': {'module': 'search_ledger',
                                   'function': 'assess_search_ledger',
                                   'schema': 'SEARCH_LEDGER_ASSESS_SCHEMA',
                                   'schema_module': 'search_ledger',
                                   'purpose': 'Сверить записи поиска с ячейками охвата.',
                                   'limitations': 'Работает в пределах поданного типизированного '
                                                  'запроса; не подтверждает внешние факты без '
                                                  'отдельного исходного чтения.',
                                   'kind': 'supplied_evidence_assessor',
                                   'group': 'Search, coverage and source acquisition / Поиск, '
                                            'охват и получение источников'},
 'research_search_coverage_details_assess': {'module': 'coverage_details',
                                             'function': 'assess_search_coverage_details',
                                             'schema': 'SEARCH_COVERAGE_DETAILS_SCHEMA',
                                             'schema_module': 'coverage_details',
                                             'purpose': 'Проверить языковые ячейки, источники и '
                                                        'показатели охвата.',
                                             'limitations': 'Работает в пределах поданного '
                                                            'типизированного запроса; не '
                                                            'подтверждает внешние факты без '
                                                            'отдельного исходного чтения.',
                                             'kind': 'supplied_evidence_assessor',
                                             'group': 'Search, coverage and source acquisition / '
                                                      'Поиск, охват и получение источников'},
 'research_fragment_verify': {'module': 'sources',
                              'function': 'verify_fragment',
                              'schema': 'FRAGMENT_VERIFY_SCHEMA',
                              'schema_module': 'sources',
                              'purpose': 'Сверить фрагмент источника с независимым чтением по '
                                         'адресу.',
                              'limitations': 'Опирается на переданные материалы и проверяющие '
                                             'записи; не получает оригинал самостоятельно.',
                              'kind': 'supplied_evidence_assessor',
                              'group': 'Search, coverage and source acquisition / Поиск, охват и '
                                       'получение источников'},
 'research_claim_evaluate': {'module': 'claims',
                             'function': 'evaluate_claim',
                             'schema': 'CLAIM_EVALUATE_SCHEMA',
                             'schema_module': 'claims',
                             'purpose': 'Оценить тезис и связи с известными фрагментами '
                                        'доказательств.',
                             'limitations': 'Оценивает переданные тезисы, фрагменты и возражения; '
                                            'отсутствие первичного чтения не превращается в '
                                            'независимую проверку.',
                             'kind': 'supplied_evidence_assessor',
                             'group': 'Search, coverage and source acquisition / Поиск, охват и '
                                      'получение источников'},
 'research_synthesis_assess': {'module': 'claims',
                               'function': 'assess_synthesis',
                               'schema': 'SYNTHESIS_ASSESS_SCHEMA',
                               'schema_module': 'claims',
                               'purpose': 'Проверить синтез тезисов и записей оспаривания.',
                               'limitations': 'Оценивает переданные тезисы, фрагменты и '
                                              'возражения; отсутствие первичного чтения не '
                                              'превращается в независимую проверку.',
                               'kind': 'supplied_evidence_assessor',
                               'group': 'Search, coverage and source acquisition / Поиск, охват и '
                                        'получение источников'},
 'research_evidence_standard_create': {'module': 'epistemics',
                                       'function': 'create_evidence_standard',
                                       'schema': 'EVIDENCE_STANDARD_CREATE_SCHEMA',
                                       'schema_module': 'epistemics',
                                       'purpose': 'Создать версионированный стандарт доказательств '
                                                  'для тезисов.',
                                       'limitations': 'Структурирует стандарт, тип или исключение '
                                                      'по переданным полям; не устанавливает '
                                                      'истинность источника.',
                                       'kind': 'supplied_evidence_assessor',
                                       'group': 'Search, coverage and source acquisition / Поиск, '
                                                'охват и получение источников'},
 'research_evidence_exception_assess': {'module': 'epistemics',
                                        'function': 'assess_evidence_exception',
                                        'schema': 'EVIDENCE_EXCEPTION_ASSESS_SCHEMA',
                                        'schema_module': 'epistemics',
                                        'purpose': 'Оценить исключение при недоступном '
                                                   'обязательном доказательстве.',
                                        'limitations': 'Структурирует стандарт, тип или исключение '
                                                       'по переданным полям; не устанавливает '
                                                       'истинность источника.',
                                        'kind': 'supplied_evidence_assessor',
                                        'group': 'Search, coverage and source acquisition / Поиск, '
                                                 'охват и получение источников'},
 'research_claim_card_assess': {'module': 'epistemics',
                                'function': 'assess_claim_card',
                                'schema': 'CLAIM_CARD_ASSESS_SCHEMA',
                                'schema_module': 'epistemics',
                                'purpose': 'Проверить карточку тезиса и тип предмета утверждения.',
                                'limitations': 'Структурирует стандарт, тип или исключение по '
                                               'переданным полям; не устанавливает истинность '
                                               'источника.',
                                'kind': 'supplied_evidence_assessor',
                                'group': 'Search, coverage and source acquisition / Поиск, охват и '
                                         'получение источников'},
 'research_negative_knowledge_classify': {'module': 'epistemics',
                                          'function': 'classify_negative_knowledge',
                                          'schema': 'NEGATIVE_KNOWLEDGE_CLASSIFY_SCHEMA',
                                          'schema_module': 'epistemics',
                                          'purpose': 'Классифицировать отрицательный поиск без '
                                                     'подмены отсутствия доказательством.',
                                          'limitations': 'Структурирует стандарт, тип или '
                                                         'исключение по переданным полям; не '
                                                         'устанавливает истинность источника.',
                                          'kind': 'supplied_evidence_assessor',
                                          'group': 'Search, coverage and source acquisition / '
                                                   'Поиск, охват и получение источников'},
 'research_decision_envelope_assess': {'module': 'decisions',
                                       'function': 'assess_decision_envelope',
                                       'schema': 'DECISION_ENVELOPE_ASSESS_SCHEMA',
                                       'schema_module': 'decisions',
                                       'purpose': 'Проверить силу и границы рекомендации.',
                                       'limitations': 'Работает в пределах поданного '
                                                      'типизированного запроса; не подтверждает '
                                                      'внешние факты без отдельного исходного '
                                                      'чтения.',
                                       'kind': 'supplied_evidence_assessor',
                                       'group': 'Architecture, quality and decisions / '
                                                'Архитектура, качество и решения'},
 'research_delta_assess': {'module': 'decisions',
                           'function': 'assess_delta',
                           'schema': 'DELTA_ASSESS_SCHEMA',
                           'schema_module': 'decisions',
                           'purpose': 'Оценить существенное изменение между базовой и текущей '
                                      'редакцией.',
                           'limitations': 'Работает в пределах поданного типизированного запроса; '
                                          'не подтверждает внешние факты без отдельного исходного '
                                          'чтения.',
                           'kind': 'supplied_evidence_assessor',
                           'group': 'Architecture, quality and decisions / Архитектура, качество и '
                                    'решения'},
 'research_incident_assess': {'module': 'decisions',
                              'function': 'assess_incident',
                              'schema': 'INCIDENT_ASSESS_SCHEMA',
                              'schema_module': 'decisions',
                              'purpose': 'Оценить инцидент по датированным источникам и тезисам.',
                              'limitations': 'Работает в пределах поданного типизированного '
                                             'запроса; не подтверждает внешние факты без '
                                             'отдельного исходного чтения.',
                              'kind': 'supplied_evidence_assessor',
                              'group': 'Architecture, quality and decisions / Архитектура, '
                                       'качество и решения'},
 'research_engagement_level_select': {'module': 'engagement',
                                      'function': 'select_engagement_level',
                                      'schema': 'ENGAGEMENT_LEVEL_SELECT_SCHEMA',
                                      'schema_module': 'engagement',
                                      'purpose': 'Выбрать уровень исследования по материалам и '
                                                 'потребности в синтезе.',
                                      'limitations': 'Работает в пределах поданного '
                                                     'типизированного запроса; не подтверждает '
                                                     'внешние факты без отдельного исходного '
                                                     'чтения.',
                                      'kind': 'supplied_evidence_assessor',
                                      'group': 'Architecture, quality and decisions / Архитектура, '
                                               'качество и решения'},
 'research_parsing_result_assess': {'module': 'engagement',
                                    'function': 'assess_parsing_result',
                                    'schema': 'PARSING_RESULT_ASSESS_SCHEMA',
                                    'schema_module': 'engagement',
                                    'purpose': 'Сверить результат разбора с хешами оригинала и '
                                               'производного текста.',
                                    'limitations': 'Работает в пределах поданного типизированного '
                                                   'запроса; не подтверждает внешние факты без '
                                                   'отдельного исходного чтения.',
                                    'kind': 'supplied_evidence_assessor',
                                    'group': 'Documents and representations / Документы и '
                                             'представления'},
 'research_unicode_representations_build': {'module': 'intake',
                                            'function': 'build_unicode_representations',
                                            'schema': 'UNICODE_REPRESENTATIONS_BUILD_SCHEMA',
                                            'schema_module': 'intake',
                                            'purpose': 'Построить точное и отображаемое '
                                                       'представления текста с проверкой похожих '
                                                       'знаков.',
                                            'limitations': 'Проверяет заголовки/версии разборщиков '
                                                           'и представления; сам по себе не читает '
                                                           'весь документ.',
                                            'kind': 'computation_or_record_build',
                                            'group': 'Documents and representations / Документы и '
                                                     'представления'},
 'research_document_graph_build': {'module': 'document_graph',
                                   'function': 'build_document_graph',
                                   'schema': 'DOCUMENT_GRAPH_BUILD_SCHEMA',
                                   'schema_module': 'document_graph',
                                   'purpose': 'Построить граф документа с привязкой к страницам и '
                                              'элементам.',
                                   'limitations': 'Строит/сверяет граф из переданного parse и '
                                                  'наблюдений; не читает пиксели и не '
                                                  'устанавливает научный смысл.',
                                   'kind': 'computation_or_record_build',
                                   'group': 'Documents and representations / Документы и '
                                            'представления'},
 'research_document_graph_verify': {'module': 'document_graph',
                                    'function': 'verify_document_graph',
                                    'schema': 'DOCUMENT_GRAPH_VERIFY_SCHEMA',
                                    'schema_module': 'document_graph',
                                    'purpose': 'Проверить граф документа по наблюдениям качества.',
                                    'limitations': 'Строит/сверяет граф из переданного parse и '
                                                   'наблюдений; не читает пиксели и не '
                                                   'устанавливает научный смысл.',
                                    'kind': 'supplied_evidence_assessor',
                                    'group': 'Documents and representations / Документы и '
                                             'представления'},
 'research_search_environment_record': {'module': 'search_workflow',
                                        'function': 'record_search_environment',
                                        'schema': 'SEARCH_ENVIRONMENT_RECORD_SCHEMA',
                                        'schema_module': 'search_workflow',
                                        'purpose': 'Зафиксировать среду исполнения поискового '
                                                   'запроса.',
                                        'limitations': 'Компилирует или проверяет предоставленную '
                                                       'стратегию/среду; не запускает внешний '
                                                       'поиск и не доказывает полноту охвата.',
                                        'kind': 'supplied_evidence_assessor',
                                        'group': 'Search methods and instruments / Поисковые '
                                                 'методы и инструменты'},
 'research_search_stop_assess': {'module': 'search_workflow',
                                 'function': 'assess_search_stop',
                                 'schema': 'SEARCH_STOP_ASSESS_SCHEMA',
                                 'schema_module': 'search_workflow',
                                 'purpose': 'Оценить остановку поиска по охвату, отдаче и остатку.',
                                 'limitations': 'Компилирует или проверяет предоставленную '
                                                'стратегию/среду; не запускает внешний поиск и не '
                                                'доказывает полноту охвата.',
                                 'kind': 'supplied_evidence_assessor',
                                 'group': 'Search methods and instruments / Поисковые методы и '
                                          'инструменты'},
 'research_screening_stop_assess': {'module': 'search_workflow',
                                    'function': 'assess_screening_stop',
                                    'schema': 'SCREENING_STOP_ASSESS_SCHEMA',
                                    'schema_module': 'search_workflow',
                                    'purpose': 'Проверить остановку отбора по решениям и правилу.',
                                    'limitations': 'Компилирует или проверяет предоставленную '
                                                   'стратегию/среду; не запускает внешний поиск и '
                                                   'не доказывает полноту охвата.',
                                    'kind': 'supplied_evidence_assessor',
                                    'group': 'Search methods and instruments / Поисковые методы и '
                                             'инструменты'},
 'research_instrument_portfolio_build': {'module': 'instruments',
                                         'function': 'build_instrument_portfolio',
                                         'schema': 'INSTRUMENT_PORTFOLIO_BUILD_SCHEMA',
                                         'schema_module': 'instruments',
                                         'purpose': 'Сформировать набор исследовательских '
                                                    'инструментов-кандидатов.',
                                         'limitations': 'Строит/сверяет портфель и запросы из '
                                                        'поданных записей; не вызывает внешний '
                                                        'инструмент.',
                                         'kind': 'computation_or_record_build',
                                         'group': 'Search methods and instruments / Поисковые '
                                                  'методы и инструменты'},
 'research_instrument_strategy_build': {'module': 'instruments',
                                        'function': 'build_instrument_strategy',
                                        'schema': 'INSTRUMENT_STRATEGY_BUILD_SCHEMA',
                                        'schema_module': 'instruments',
                                        'purpose': 'Построить стратегию из версионированного '
                                                   'набора инструментов.',
                                        'limitations': 'Строит/сверяет портфель и запросы из '
                                                       'поданных записей; не вызывает внешний '
                                                       'инструмент.',
                                        'kind': 'computation_or_record_build',
                                        'group': 'Search methods and instruments / Поисковые '
                                                 'методы и инструменты'},
 'research_tool_query_build': {'module': 'instruments',
                               'function': 'build_tool_query',
                               'schema': 'TOOL_QUERY_BUILD_SCHEMA',
                               'schema_module': 'instruments',
                               'purpose': 'Составить запрос к инструменту по элементу стратегии.',
                               'limitations': 'Строит/сверяет портфель и запросы из поданных '
                                              'записей; не вызывает внешний инструмент.',
                               'kind': 'computation_or_record_build',
                               'group': 'Search methods and instruments / Поисковые методы и '
                                        'инструменты'},
 'research_brief_build': {'module': 'briefing',
                          'function': 'build_brief',
                          'schema': 'BRIEF_BUILD_SCHEMA',
                          'schema_module': 'briefing',
                          'purpose': 'Составить структурированное задание из вопроса и '
                                     'предпосылок.',
                          'limitations': 'Работает в пределах поданного типизированного запроса; '
                                         'не подтверждает внешние факты без отдельного исходного '
                                         'чтения.',
                          'kind': 'computation_or_record_build',
                          'group': 'Framing, context and oversight / Постановка, контекст и '
                                   'контроль'},
 'research_contextualization_build': {'module': 'briefing',
                                      'function': 'build_contextualization',
                                      'schema': 'CONTEXTUALIZATION_BUILD_SCHEMA',
                                      'schema_module': 'briefing',
                                      'purpose': 'Сформировать предметный, адресный и языковой '
                                                 'контекст задачи.',
                                      'limitations': 'Работает в пределах поданного '
                                                     'типизированного запроса; не подтверждает '
                                                     'внешние факты без отдельного исходного '
                                                     'чтения.',
                                      'kind': 'computation_or_record_build',
                                      'group': 'Framing, context and oversight / Постановка, '
                                               'контекст и контроль'},
 'research_assurance_profile_assess': {'module': 'governance',
                                       'function': 'assess_assurance_profile',
                                       'schema': 'ASSURANCE_PROFILE_ASSESS_SCHEMA',
                                       'schema_module': 'governance',
                                       'purpose': 'Проверить профиль обоснованности по риску и '
                                                  'уровню доказательств.',
                                       'limitations': 'Работает в пределах поданного '
                                                      'типизированного запроса; не подтверждает '
                                                      'внешние факты без отдельного исходного '
                                                      'чтения.',
                                       'kind': 'supplied_evidence_assessor',
                                       'group': 'Framing, context and oversight / Постановка, '
                                                'контекст и контроль'},
 'research_role_profile_assess': {'module': 'collaboration',
                                  'function': 'assess_role_profile',
                                  'schema': 'ROLE_PROFILE_ASSESS_SCHEMA',
                                  'schema_module': 'collaboration',
                                  'purpose': 'Проверить заявленный профиль исследовательской роли.',
                                  'limitations': 'Проверяет заявленные роли, контексты и позиции; '
                                                 'несколько согласных моделей не становятся '
                                                 'независимыми источниками.',
                                  'kind': 'supplied_evidence_assessor',
                                  'group': 'Roles, collaboration and modality / Роли, '
                                           'взаимодействие и модальности'},
 'research_role_independence_assess': {'module': 'collaboration',
                                       'function': 'assess_role_independence',
                                       'schema': 'ROLE_INDEPENDENCE_ASSESS_SCHEMA',
                                       'schema_module': 'collaboration',
                                       'purpose': 'Проверить независимость заявленных ролей.',
                                       'limitations': 'Проверяет заявленные роли, контексты и '
                                                      'позиции; несколько согласных моделей не '
                                                      'становятся независимыми источниками.',
                                       'kind': 'supplied_evidence_assessor',
                                       'group': 'Roles, collaboration and modality / Роли, '
                                                'взаимодействие и модальности'},
 'research_consilium_plan_assess': {'module': 'collaboration',
                                    'function': 'assess_consilium_plan',
                                    'schema': 'CONSILIUM_PLAN_ASSESS_SCHEMA',
                                    'schema_module': 'collaboration',
                                    'purpose': 'Проверить план совещания ролей и раздельность '
                                               'входов.',
                                    'limitations': 'Проверяет заявленные роли, контексты и '
                                                   'позиции; несколько согласных моделей не '
                                                   'становятся независимыми источниками.',
                                    'kind': 'supplied_evidence_assessor',
                                    'group': 'Roles, collaboration and modality / Роли, '
                                             'взаимодействие и модальности'},
 'research_consilium_result_assess': {'module': 'collaboration',
                                      'function': 'assess_consilium_result',
                                      'schema': 'CONSILIUM_RESULT_ASSESS_SCHEMA',
                                      'schema_module': 'collaboration',
                                      'purpose': 'Проверить раунды, позиции и ограничения '
                                                 'совещания.',
                                      'limitations': 'Проверяет заявленные роли, контексты и '
                                                     'позиции; несколько согласных моделей не '
                                                     'становятся независимыми источниками.',
                                      'kind': 'supplied_evidence_assessor',
                                      'group': 'Roles, collaboration and modality / Роли, '
                                               'взаимодействие и модальности'},
 'research_topology_select': {'module': 'collaboration',
                              'function': 'select_topology',
                              'schema': 'TOPOLOGY_SELECT_SCHEMA',
                              'schema_module': 'collaboration',
                              'purpose': 'Выбрать схему работы по числу и связанности ветвей.',
                              'limitations': 'Проверяет заявленные роли, контексты и позиции; '
                                             'несколько согласных моделей не становятся '
                                             'независимыми источниками.',
                              'kind': 'supplied_evidence_assessor',
                              'group': 'Roles, collaboration and modality / Роли, взаимодействие и '
                                       'модальности'},
 'research_modality_plan_assess': {'module': 'collaboration',
                                   'function': 'assess_modality_plan',
                                   'schema': 'MODALITY_PLAN_ASSESS_SCHEMA',
                                   'schema_module': 'collaboration',
                                   'purpose': 'Проверить модальности входных данных плана.',
                                   'limitations': 'Проверяет заявленные роли, контексты и позиции; '
                                                  'несколько согласных моделей не становятся '
                                                  'независимыми источниками.',
                                   'kind': 'supplied_evidence_assessor',
                                   'group': 'Roles, collaboration and modality / Роли, '
                                            'взаимодействие и модальности'},
 'research_fact_map_build': {'module': 'knowledge',
                             'function': 'build_fact_map',
                             'schema': 'FACT_MAP_BUILD_SCHEMA',
                             'schema_module': 'knowledge',
                             'purpose': 'Построить карту фактов, связанную с редакцией '
                                        'авторитетного состояния.',
                             'limitations': 'Работает в пределах поданного типизированного '
                                            'запроса; не подтверждает внешние факты без отдельного '
                                            'исходного чтения.',
                             'kind': 'computation_or_record_build',
                             'group': 'Knowledge, narrative and provenance / Знание, изложение и '
                                      'происхождение'},
 'research_root_cause_map_build': {'module': 'knowledge',
                                   'function': 'build_root_cause_map',
                                   'schema': 'ROOT_CAUSE_MAP_BUILD_SCHEMA',
                                   'schema_module': 'knowledge',
                                   'purpose': 'Построить карту причин по узлам и связям.',
                                   'limitations': 'Работает в пределах поданного типизированного '
                                                  'запроса; не подтверждает внешние факты без '
                                                  'отдельного исходного чтения.',
                                   'kind': 'computation_or_record_build',
                                   'group': 'Knowledge, narrative and provenance / Знание, '
                                            'изложение и происхождение'},
 'research_narrative_plan_assess': {'module': 'narrative',
                                    'function': 'assess_narrative_plan',
                                    'schema': 'NARRATIVE_PLAN_ASSESS_SCHEMA',
                                    'schema_module': 'narrative',
                                    'purpose': 'Проверить план изложения с учётом аудитории и '
                                               'решения.',
                                    'limitations': 'Работает в пределах поданного типизированного '
                                                   'запроса; не подтверждает внешние факты без '
                                                   'отдельного исходного чтения.',
                                    'kind': 'supplied_evidence_assessor',
                                    'group': 'Knowledge, narrative and provenance / Знание, '
                                             'изложение и происхождение'},
 'research_attribution_assess': {'module': 'attribution',
                                 'function': 'assess_attribution',
                                 'schema': 'ATTRIBUTION_ASSESS_SCHEMA',
                                 'schema_module': 'attribution',
                                 'purpose': 'Проверить происхождение тезиса, цитаты, генерации и '
                                            'сверки.',
                                 'limitations': 'Сверяет связи тезиса/цитаты и чувствительность к '
                                                'поданным происхождениям; совпадение адреса не '
                                                'доказывает смысл.',
                                 'kind': 'supplied_evidence_assessor',
                                 'group': 'Knowledge, narrative and provenance / Знание, изложение '
                                          'и происхождение'},
 'research_source_influence_assess': {'module': 'attribution',
                                      'function': 'assess_source_influence',
                                      'schema': 'SOURCE_INFLUENCE_ASSESS_SCHEMA',
                                      'schema_module': 'attribution',
                                      'purpose': 'Оценить влияние происхождения источников на '
                                                 'выводы при исключениях.',
                                      'limitations': 'Сверяет связи тезиса/цитаты и '
                                                     'чувствительность к поданным происхождениям; '
                                                     'совпадение адреса не доказывает смысл.',
                                      'kind': 'supplied_evidence_assessor',
                                      'group': 'Knowledge, narrative and provenance / Знание, '
                                               'изложение и происхождение'},
 'research_narrative_diff_assess': {'module': 'attribution',
                                    'function': 'assess_narrative_diff',
                                    'schema': 'NARRATIVE_DIFF_ASSESS_SCHEMA',
                                    'schema_module': 'attribution',
                                    'purpose': 'Проверить изменения между этапами изложения.',
                                    'limitations': 'Сверяет связи тезиса/цитаты и чувствительность '
                                                   'к поданным происхождениям; совпадение адреса '
                                                   'не доказывает смысл.',
                                    'kind': 'supplied_evidence_assessor',
                                    'group': 'Knowledge, narrative and provenance / Знание, '
                                             'изложение и происхождение'},
 'research_living_review_assess': {'module': 'provenance',
                                   'function': 'assess_living_review',
                                   'schema': 'LIVING_REVIEW_ASSESS_SCHEMA',
                                   'schema_module': 'provenance',
                                   'purpose': 'Проверить обновление продолжаемого обзора по '
                                              'правилам и базе.',
                                   'limitations': 'Проверяет поданные графы/манифесты/события; не '
                                                  'получает оригиналы заново.',
                                   'kind': 'supplied_evidence_assessor',
                                   'group': 'Knowledge, narrative and provenance / Знание, '
                                            'изложение и происхождение'},
 'research_deep_qualification_assess': {'module': 'deep_qualification',
                                        'function': 'assess_deep_qualification',
                                        'schema': 'DEEP_QUALIFICATION_ASSESS_SCHEMA',
                                        'schema_module': 'deep_qualification',
                                        'purpose': 'Проверить ограниченный набор Deep/Ultra, '
                                                   'запуски и перекрёстные проверки.',
                                        'limitations': 'Считает вектор по предоставленным '
                                                       'runs/cross_checks; controlled_fixture не '
                                                       'равен live qualification.',
                                        'kind': 'supplied_evidence_assessor',
                                        'group': 'Depth qualification and recovery / Квалификация '
                                                 'глубины и восстановление'},
 'research_obligation_preservation_assess': {'module': 'deep_qualification',
                                             'function': 'assess_obligation_preservation',
                                             'schema': 'OBLIGATION_PRESERVATION_ASSESS_SCHEMA',
                                             'schema_module': 'deep_qualification',
                                             'purpose': 'Проверить сохранение обязательств после '
                                                        'контрольной точки.',
                                             'limitations': 'Считает вектор по предоставленным '
                                                            'runs/cross_checks; controlled_fixture '
                                                            'не равен live qualification.',
                                             'kind': 'supplied_evidence_assessor',
                                             'group': 'Depth qualification and recovery / '
                                                      'Квалификация глубины и восстановление'},
 'research_multiagent_independence_assess': {'module': 'deep_qualification',
                                             'function': 'assess_multiagent_independence',
                                             'schema': 'MULTIAGENT_INDEPENDENCE_ASSESS_SCHEMA',
                                             'schema_module': 'deep_qualification',
                                             'purpose': 'Проверить общие каналы ошибок и согласие '
                                                        'ролей.',
                                             'limitations': 'Считает вектор по предоставленным '
                                                            'runs/cross_checks; controlled_fixture '
                                                            'не равен live qualification.',
                                             'kind': 'supplied_evidence_assessor',
                                             'group': 'Depth qualification and recovery / '
                                                      'Квалификация глубины и восстановление'},
 'research_resilience_recovery_assess': {'module': 'deep_qualification',
                                         'function': 'assess_resilience_recovery',
                                         'schema': 'RESILIENCE_RECOVERY_ASSESS_SCHEMA',
                                         'schema_module': 'deep_qualification',
                                         'purpose': 'Проверить восстановление после отказа '
                                                    'поставщика, дрейфа или перезапуска.',
                                         'limitations': 'Считает вектор по предоставленным '
                                                        'runs/cross_checks; controlled_fixture не '
                                                        'равен live qualification.',
                                         'kind': 'supplied_evidence_assessor',
                                         'group': 'Depth qualification and recovery / Квалификация '
                                                  'глубины и восстановление'},
 'research_provider_fallback_assess': {'module': 'provider_contracts',
                                       'function': 'assess_provider_fallback',
                                       'schema': 'PROVIDER_FALLBACK_ASSESS_SCHEMA',
                                       'schema_module': 'provider_contracts',
                                       'purpose': 'Проверить соответствие резервного маршрута '
                                                  'обязательным свойствам.',
                                       'limitations': 'Оценивает поданные манифесты и квитанции; '
                                                      'не доказывает доступ или успешность живого '
                                                      'провайдера без отдельной пробы.',
                                       'kind': 'supplied_evidence_assessor',
                                       'group': 'Providers and capabilities / Поставщики и '
                                                'возможности'},
 'research_scholarly_object_resolve': {'module': 'scholarly',
                                       'function': 'resolve_scholarly_object',
                                       'schema': 'SCHOLARLY_OBJECT_RESOLVE_SCHEMA',
                                       'schema_module': 'scholarly',
                                       'purpose': 'Сопоставить научные записи с ограниченной '
                                                  'идентичностью объекта.',
                                       'limitations': 'Работает в пределах поданного '
                                                      'типизированного запроса; не подтверждает '
                                                      'внешние факты без отдельного исходного '
                                                      'чтения.',
                                       'kind': 'supplied_evidence_assessor',
                                       'group': 'Providers and capabilities / Поставщики и '
                                                'возможности'},
 'research_capability_gap_assess': {'module': 'scholarly',
                                    'function': 'assess_capability_gap',
                                    'schema': 'CAPABILITY_GAP_ASSESS_SCHEMA',
                                    'schema_module': 'scholarly',
                                    'purpose': 'Сверить требуемые и квалифицированные возможности.',
                                    'limitations': 'Работает в пределах поданного типизированного '
                                                   'запроса; не подтверждает внешние факты без '
                                                   'отдельного исходного чтения.',
                                    'kind': 'supplied_evidence_assessor',
                                    'group': 'Providers and capabilities / Поставщики и '
                                             'возможности'},
 'research_academic_integrity_assess': {'module': 'academic_integrity',
                                        'function': 'assess_academic_integrity',
                                        'schema': 'ACADEMIC_INTEGRITY_ASSESS_SCHEMA',
                                        'schema_module': 'academic_integrity',
                                        'purpose': 'Проверить типизированный контроль научной '
                                                   'добросовестности.',
                                        'limitations': 'Применяет типизированные академические '
                                                       'проверки к поданным данным; не заменяет '
                                                       'чтение оригиналов.',
                                        'kind': 'supplied_evidence_assessor',
                                        'group': 'Business and academic methods / Деловые и '
                                                 'научные методы'},
 'research_meta_analysis_assess': {'module': 'academic',
                                   'function': 'assess_meta_analysis',
                                   'schema': 'META_ANALYSIS_ASSESS_SCHEMA',
                                   'schema_module': 'academic',
                                   'purpose': 'Проверить допустимость объединения результатов и '
                                              'чувствительность.',
                                   'limitations': 'Проверяет pooling и наличие нужной '
                                                  'чувствительности по готовым результатам; оценку '
                                                  'эффекта вычисляет отдельный '
                                                  'fixed_effect_compute.',
                                   'kind': 'supplied_evidence_assessor',
                                   'group': 'Business and academic methods / Деловые и научные '
                                            'методы'},
 'research_review_protocol_validate': {'module': 'advanced_academic',
                                       'function': 'validate_review_protocol',
                                       'schema': 'REVIEW_PROTOCOL_VALIDATE_SCHEMA',
                                       'schema_module': 'advanced_academic',
                                       'purpose': 'Проверить протокол обзора и поправки к нему.',
                                       'limitations': 'Проверяет либо вычисляет только поданные '
                                                      'записи и указанные версии; визуальное '
                                                      'чтение PDF и независимое воспроизведение не '
                                                      'подразумеваются.',
                                       'kind': 'supplied_evidence_assessor',
                                       'group': 'Business and academic methods / Деловые и научные '
                                                'методы'},
 'research_screening_adjudicate': {'module': 'advanced_academic',
                                   'function': 'adjudicate_screening',
                                   'schema': 'SCREENING_ADJUDICATE_SCHEMA',
                                   'schema_module': 'advanced_academic',
                                   'purpose': 'Проверить решения отбора и разрешение разногласий.',
                                   'limitations': 'Проверяет либо вычисляет только поданные записи '
                                                  'и указанные версии; визуальное чтение PDF и '
                                                  'независимое воспроизведение не подразумеваются.',
                                   'kind': 'supplied_evidence_assessor',
                                   'group': 'Business and academic methods / Деловые и научные '
                                            'методы'},
 'research_study_graph_resolve': {'module': 'advanced_academic',
                                  'function': 'resolve_study_graph',
                                  'schema': 'STUDY_GRAPH_RESOLVE_SCHEMA',
                                  'schema_module': 'advanced_academic',
                                  'purpose': 'Сопоставить узлы, связи и квитанции полного текста '
                                             'исследования.',
                                  'limitations': 'Проверяет либо вычисляет только поданные записи '
                                                 'и указанные версии; визуальное чтение PDF и '
                                                 'независимое воспроизведение не подразумеваются.',
                                  'kind': 'supplied_evidence_assessor',
                                  'group': 'Business and academic methods / Деловые и научные '
                                           'методы'},
 'research_prisma_assess': {'module': 'advanced_academic',
                            'function': 'assess_prisma',
                            'schema': 'PRISMA_ASSESS_SCHEMA',
                            'schema_module': 'advanced_academic',
                            'purpose': 'Проверить применимые пункты PRISMA и их подтверждения.',
                            'limitations': 'Проверяет либо вычисляет только поданные записи и '
                                           'указанные версии; визуальное чтение PDF и независимое '
                                           'воспроизведение не подразумеваются.',
                            'kind': 'supplied_evidence_assessor',
                            'group': 'Business and academic methods / Деловые и научные методы'},
 'research_prisma_flow_account': {'module': 'advanced_academic',
                                  'function': 'assess_prisma_flow_accounting',
                                  'schema': 'PRISMA_FLOW_ACCOUNT_SCHEMA',
                                  'schema_module': 'advanced_academic',
                                  'purpose': 'Учесть решения по полным текстам в схеме PRISMA.',
                                  'limitations': 'Проверяет либо вычисляет только поданные записи '
                                                 'и указанные версии; визуальное чтение PDF и '
                                                 'независимое воспроизведение не подразумеваются.',
                                  'kind': 'supplied_evidence_assessor',
                                  'group': 'Business and academic methods / Деловые и научные '
                                           'методы'},
 'research_risk_of_bias_assess': {'module': 'advanced_academic',
                                  'function': 'assess_risk_of_bias',
                                  'schema': 'RISK_OF_BIAS_ASSESS_SCHEMA',
                                  'schema_module': 'advanced_academic',
                                  'purpose': 'Проверить зарегистрированные оценки риска смещения.',
                                  'limitations': 'Проверяет либо вычисляет только поданные записи '
                                                 'и указанные версии; визуальное чтение PDF и '
                                                 'независимое воспроизведение не подразумеваются.',
                                  'kind': 'supplied_evidence_assessor',
                                  'group': 'Business and academic methods / Деловые и научные '
                                           'методы'},
 'research_certainty_assess': {'module': 'advanced_academic',
                               'function': 'assess_certainty',
                               'schema': 'CERTAINTY_ASSESS_SCHEMA',
                               'schema_module': 'advanced_academic',
                               'purpose': 'Оценить определённость вывода по исходу и областям '
                                          'риска.',
                               'limitations': 'Проверяет либо вычисляет только поданные записи и '
                                              'указанные версии; визуальное чтение PDF и '
                                              'независимое воспроизведение не подразумеваются.',
                               'kind': 'supplied_evidence_assessor',
                               'group': 'Business and academic methods / Деловые и научные методы'},
 'research_profile_qualification': {'module': 'qualification',
                                    'function': 'evaluate_profile_qualification',
                                    'schema': 'PROFILE_QUALIFICATION_SCHEMA',
                                    'schema_module': 'qualification',
                                    'purpose': 'Проверить доказательства квалификации именованного '
                                               'профиля и набора.',
                                    'limitations': 'Сравнивает поданные результаты/профили и '
                                                   'затраты; не создаёт испытательный корпус и не '
                                                   'измеряет независимую истинность.',
                                    'kind': 'supplied_evidence_assessor',
                                    'group': 'Deployment and Foundation integration / '
                                             'Развёртывание и интеграция Foundation'},
 'research_depth_compare': {'module': 'qualification',
                            'function': 'compare_depths',
                            'schema': 'DEPTH_COMPARISON_SCHEMA',
                            'schema_module': 'qualification',
                            'purpose': 'Сравнить Search, Deep и Ultra при общих ограничениях '
                                       'задачи.',
                            'limitations': 'Сравнивает поданные результаты/профили и затраты; не '
                                           'создаёт испытательный корпус и не измеряет независимую '
                                           'истинность.',
                            'kind': 'supplied_evidence_assessor',
                            'group': 'Deployment and Foundation integration / Развёртывание и '
                                     'интеграция Foundation'},
 'research_utility_assess': {'module': 'qualification',
                             'function': 'assess_utility',
                             'schema': 'UTILITY_ASSESS_SCHEMA',
                             'schema_module': 'qualification',
                             'purpose': 'Оценить полезность результата, экономию времени и труд '
                                        'проверки.',
                             'limitations': 'Сравнивает поданные результаты/профили и затраты; не '
                                            'создаёт испытательный корпус и не измеряет '
                                            'независимую истинность.',
                             'kind': 'supplied_evidence_assessor',
                             'group': 'Deployment and Foundation integration / Развёртывание и '
                                      'интеграция Foundation'},
 'research_fragment_promote': {'module': 'evidence',
                               'function': 'promote_fragment',
                               'schema': 'FRAGMENT_PROMOTE_SCHEMA',
                               'schema_module': 'schemas',
                               'purpose': 'Проверить повышение фрагмента до доказательного класса.',
                               'limitations': 'Работает в пределах поданного типизированного '
                                              'запроса; не подтверждает внешние факты без '
                                              'отдельного исходного чтения.',
                               'kind': 'supplied_evidence_assessor',
                               'group': 'Deployment and Foundation integration / Развёртывание и '
                                        'интеграция Foundation'},
 'research_r3_evidence_assess': {'module': 'r3_evidence',
                                 'function': 'assess_r3_evidence_field',
                                 'schema': 'R3_EVIDENCE_SCHEMA',
                                 'schema_module': 'r3_evidence',
                                 'purpose': 'Проверить пакеты доказательств из официального '
                                            'документа, набора данных и атомов.',
                                 'limitations': 'Работает в пределах поданного типизированного '
                                                'запроса; не подтверждает внешние факты без '
                                                'отдельного исходного чтения.',
                                 'kind': 'supplied_evidence_assessor',
                                 'group': 'Deployment and Foundation integration / Развёртывание и '
                                          'интеграция Foundation'},
 'research_context_package_assemble': {'module': 'runtime_contracts',
                                       'function': 'assemble_context_package',
                                       'schema': 'CONTEXT_ASSEMBLY_SCHEMA',
                                       'schema_module': 'runtime_contracts',
                                       'purpose': 'Собрать ограниченные вклады в контекст для '
                                                  'получателя.',
                                       'limitations': 'Проверяет переданные эксплуатационные '
                                                      'объекты/состояния; не означает '
                                                      'автоматического исполнения внешнего '
                                                      'действия.',
                                       'kind': 'computation_or_record_build',
                                       'group': 'Deployment and Foundation integration / '
                                                'Развёртывание и интеграция Foundation'}}

GUIDES = {"decomposition": "decomposition.md", "evidence": "evidence-methods.md", "foundations": "knowledge-foundations.md", "search_loops": "search-narrative-loops.md"}


def method(args):
    action = args.get("action", "catalogue")
    name = args.get("method")
    if action == "catalogue" and args.get("scope") == "specialists":
        group = args.get("group")
        if group is None:
            from collections import Counter
            return {"groups": dict(Counter(v["group"] for v in SPECIALISTS.values())), "usage": "Select a group to discover optional offline specialist operations. No network probes or universal gate chain."}
        return {"methods": [{"method": k, "purpose": v["purpose"], "kind": v["kind"]} for k,v in SPECIALISTS.items() if v["group"] == group]}
    if action == "catalogue":
        return {"methods": [{"method": k, "purpose": v["purpose"], "kind": v["kind"]} for k,v in METHODS.items()],
                "guides": list(GUIDES), "usage": "Choose for a specific question. Describe one method to load its inputs and limitations. Assessors check submitted records; they do not search, read or validate external truth."}
    if action == "guide":
        if name not in GUIDES:
            raise ValueError("Choose a guide from catalogue")
        p = Path(__file__).resolve().parents[2] / "skills/research/references" / GUIDES[name]
        return {"guide": name, "path": str(p), "content": p.read_text(encoding="utf-8")}
    available = {**METHODS, **SPECIALISTS}
    if name not in available:
        raise ValueError("Unknown method; use catalogue")
    entry = available[name]
    module = importlib.import_module("." + entry["module"], __package__)
    if action == "describe":
        return {"method": name, **entry, "input_schema": getattr(importlib.import_module("." + entry["schema_module"], __package__), entry["schema"])}
    if action != "run" or not isinstance(args.get("input"), dict):
        raise ValueError("Use run with the input object described by the selected method")
    result = getattr(module, entry["function"])(args["input"])
    return {"method": name, "kind": entry["kind"], "result": result, "limitations": entry["limitations"],
            "scope": "The named computation/assessment only. An adverse result identifies a local limitation; it does not stop other research or erase material."}


METHOD_SCHEMA = {"name": "research_method", "description": "Select, inspect and run reviewed scientific/business research methods on demand; read decomposition/evidence guides. Includes query compilation, constructs, source independence, comparison/synthesis and numerical checks. No universal approval chain.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["catalogue", "guide", "describe", "run"]}, "method": {"type": "string"}, "scope": {"type": "string", "enum": ["core", "specialists"]}, "group": {"type": "string"}, "input": {"type": "object", "additionalProperties": True}}, "required": ["action"], "additionalProperties": False}}
