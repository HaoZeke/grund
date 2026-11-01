# frozen_string_literal: true

require 'minitest/autorun'
require 'json'
require_relative 'grund_cell_claim_rail'

class CellClaimTest < Minitest::Test
  def setup
    @rail = Grund::CellClaimRail.new
  end

  def test_population_country_of_birth_is_blocked
    result = check(sentence('304,795'), payload(
      'How many people lived in Iceland on 1 January 2026?',
      claim('304795', '304,795', 'level', [cell('MAN12103', '304795', '2026', { 'Country of birth' => 'Iceland', 'Year' => '2026' }, { 'Country of birth' => 'subgroup', 'Year' => 'time' })]),
      periods: ['2026']
    ))
    assert_equal :blocked, result.status
    assert_includes result.categories, 'unsupported_cell'
  end

  def test_headline_population_passes
    result = check(sentence('394,324'), payload(
      'How many people lived in Iceland on 1 January 2026?',
      claim('394324', '394,324', 'level', [cell('MAN00000', '394324', '2026', { 'Unit' => 'Total', 'Year' => '2026' }, { 'Unit' => 'total', 'Year' => 'time' })]),
      periods: ['2026']
    ))
    assert_equal :passed, result.status
    assert result.certain?
  end

  def test_recomputed_percent_change
    cells = [
      cell('VIS01000', '100', '2024', { 'Year' => '2024' }, { 'Year' => 'time' }),
      cell('VIS01000', '110', '2025', { 'Year' => '2025' }, { 'Year' => 'time' })
    ]
    cells.each { |cited| cited['title'] = 'Consumer price index' }
    text = 'In 2025, the index was 10 percent. That is the change from 100 (2024) to 110 (2025).'
    result = check(text, payload(
      'By what percentage did the index rise from 2024 to 2025?',
      claim('10', '10 percent', 'yoy_pct', cells),
      periods: %w[2024 2025]
    ))
    assert_equal :passed, result.status
  end

  def test_a_share_rejects_the_part_count
    cells = [
      cell('MAN00101', '190000', '2024', { 'Sex' => 'Females', 'Year' => '2024' }, { 'Sex' => 'subgroup', 'Year' => 'time' }),
      cell('MAN00101', '383000', '2024', { 'Sex' => 'Total', 'Year' => '2024' }, { 'Sex' => 'total', 'Year' => 'time' })
    ]
    bad = claim('190000', '190,000', 'share', cells)
    bad['inputs'] = %w[190000 383000]
    result = check('The share was 190,000.', payload(
      'What percentage of the population in 2024 was females?',
      bad,
      periods: ['2024'],
      named: { 'sex' => 'Females' }
    ))
    assert_equal :blocked, result.status
    assert_includes result.categories, 'wrong_number'
  end

  def test_a_share_accepts_the_recomputed_percent
    cells = [
      cell('MAN00101', '190000', '2024', { 'Sex' => 'Females', 'Year' => '2024' }, { 'Sex' => 'subgroup', 'Year' => 'time' }),
      cell('MAN00101', '383000', '2024', { 'Sex' => 'Total', 'Year' => '2024' }, { 'Sex' => 'total', 'Year' => 'time' })
    ]
    good = claim('49.6', '49.6 percent', 'share', cells)
    good['inputs'] = %w[190000 383000]
    text = 'In 2024, the share was 49.6 percent. The part is 190,000 of 383,000.'
    result = check(text, payload(
      'What percentage of the population in 2024 was females?',
      good,
      periods: ['2024'],
      named: { 'sex' => 'Females' }
    ))
    assert_equal :passed, result.status, result.reason
  end

  def test_a_two_place_sum_must_add_both_named_cells
    question = 'Hve margir bjuggu samtals í Reykjavík og Kópavogi 1. janúar 2026?'
    one = cell('MAN03200', '36943', '2026', { 'Municipality' => 'Reykjavík', 'Year' => '2026' }, { 'Municipality' => 'subgroup', 'Year' => 'time' })
    result = check('The figure was 36943.', payload(question, claim('36943', '36943', 'level', [one]), periods: ['2026']))
    assert_equal :blocked, result.status
    assert_includes result.categories, 'unsupported_cell'

    both = [
      cell('MAN04203', '139804', '2026', { 'Municipality' => 'Reykjavík', 'Year' => '2026' }, { 'Municipality' => 'subgroup', 'Year' => 'time' }),
      cell('MAN04203', '40286', '2026', { 'Municipality' => 'Kópavogur', 'Year' => '2026' }, { 'Municipality' => 'subgroup', 'Year' => 'time' })
    ]
    wrong = claim('36943', '36.943', 'sum', both)
    blocked = check('The figure was 36943.', payload(question, wrong, periods: ['2026']))
    assert_equal :blocked, blocked.status
    assert_includes blocked.categories, 'wrong_number'

    right = claim('180090', '180.090', 'sum', both)
    passed = check('The figure was 180090.', payload(question, right, periods: ['2026']))
    assert_equal :passed, passed.status, passed.reason
  end

  def test_immigrant_stock_is_not_arrivals_in_the_year
    question = 'How many immigrants lived in Iceland in 2026?'
    stock = cell('MAN43000', '77226', '2026', { 'Origin' => 'Immigrant', 'Age' => 'Total', 'Sex' => 'Total', 'Year' => '2026' }, { 'Year' => 'time', 'Origin' => 'subgroup' })
    stock['title'] = 'Population by origin, sex and age 1996-2026'
    blocked = check(sentence('77226'), payload(question, claim('77226', '77,226', 'level', [stock]), periods: ['2026']))
    assert_equal :blocked, blocked.status
    assert_includes blocked.categories, 'unsupported_cell'

    flow = cell('MAN01404', '18674', '2026', { 'Unit' => 'Immigrants', 'Sex' => 'Total', 'Year' => '2026' }, { 'Year' => 'time', 'Sex' => 'total' })
    flow['title'] = 'External migration by sex'
    passed = check(sentence('18674'), payload(question, claim('18674', '18,674', 'level', [flow]), periods: ['2026']))
    assert_equal :passed, passed.status, passed.reason
  end

  def test_a_census_year_does_not_answer_a_later_year
    question = 'How many immigrants lived in Iceland in 2026?'
    cited = cell('CEN1205', '24398', '1981', { 'Origin' => 'Immigrants', 'Year' => '1981' }, { 'Origin' => 'subgroup', 'Year' => 'time' })
    result = check('The figure was 24398.', payload(question, claim('24398', '24398', 'level', [cited]), periods: ['2026']))
    assert_equal :blocked, result.status
    assert_includes result.categories, 'unsupported_cell'
    assert_match(/period/, result.reason)
  end

  def test_a_count_is_not_answered_by_a_rate
    question = 'How many people live in Iceland?'
    cited = cell('HEI11501', '2.6', '2024', { 'Unit' => 'Children per woman' }, { 'Unit' => 'total' })
    cited['title'] = 'Total fertility rate'
    result = check('The figure was 2.6.', payload(question, claim('2.6', '2.6', 'level', [cited])))
    assert_equal :blocked, result.status
  end

  def test_a_count_is_not_answered_by_a_share_of_people
    question = 'Hver er mannfjöldi Íslands?'
    cited = cell('HEI11100', '11.6', '2024', { 'Unit' => 'Hlutfall' }, { 'Unit' => 'total' })
    cited['title'] = 'Hlutfall innflytjenda'
    result = check('Talan var 11.6.', payload(question, claim('11.6', '11.6', 'level', [cited])))
    assert_equal :blocked, result.status
  end

  def test_an_exchange_rate_needs_a_currency_unit
    question = 'What is the exchange rate of the US dollar?'
    cited = cell('PEN01103', '40.8', '2024', { 'Unit' => 'Percent of GDP' }, { 'Unit' => 'total' })
    cited['title'] = 'Long-term foreign debt'
    result = check('The figure was 40.8.', payload(question, claim('40.8', '40.8', 'level', [cited])))
    assert_equal :blocked, result.status
  end

  def test_gdp_needs_a_gdp_series
    question = "What was Iceland's GDP in 2025?"
    cited = cell('THJ05311', '676458', '2025', { 'Unit' => 'Millions' }, { 'Unit' => 'total', 'Year' => 'time' })
    cited['labels']['Year'] = '2025'
    cited['period'] = '2025'
    cited['title'] = 'Local government revenue'
    result = check('The figure was 676458.', payload(question, claim('676458', '676458', 'level', [cited]), periods: ['2025']))
    assert_equal :blocked, result.status
  end

  def test_no_period_cannot_be_answered_by_a_census_year
    question = 'Hve margir búa í Reykjavík?'
    cited = cell('CEN0012', '83502', '1981', { 'Year' => '1981' }, { 'Year' => 'time' })
    cited['title'] = 'Census of Reykjavík 1981'
    result = check('The figure was 83502.', payload(question, claim('83502', '83502', 'level', [cited])))
    assert_equal :blocked, result.status
  end

  def test_a_same_year_share_recomputes_only_when_the_flag_is_on
    cells = [
      cell('MAN00101', '189623', '2018', { 'Kyn' => 'Konur', 'Aldur' => 'Alls', 'Ár' => '2018' }, { 'Ár' => 'time' }),
      cell('MAN00101', '385000', '2018', { 'Kyn' => 'Alls', 'Aldur' => 'Alls', 'Ár' => '2018' }, { 'Ár' => 'time' })
    ]
    question = 'Hversu hátt hlutfall íbúa voru konur árið 2018? Svaraðu í prósentum.'
    stated = claim('49.3', '49.3', 'share', cells)
    text = 'The share was 49.3 percent. The part is 189623 of 385000.'
    ENV.delete('GRUND_SHARE_RECOMPUTE')
    blocked = check(text, payload(question, stated, periods: ['2018']))
    assert_equal :blocked, blocked.status

    ENV['GRUND_SHARE_RECOMPUTE'] = '1'
    passed = check(text, payload(question, stated, periods: ['2018']))
    assert_equal :passed, passed.status, passed.reason
  ensure
    ENV.delete('GRUND_SHARE_RECOMPUTE')
  end

  def test_label_digit_is_not_a_free_figure
    cited = cell('LAN05002', '-2149', '2024', { 'Account' => '01-02-04 Depreciation', 'Year' => '2024' }, { 'Account' => 'subgroup', 'Year' => 'time' })
    result = check('The figure was 4.', payload(
      'What was 01-02-04 Depreciation in 2024?',
      claim('-2149', '-2,149', 'level', [cited]),
      periods: ['2024']
    ))
    assert_equal :blocked, result.status
    assert_includes result.categories, 'ungrounded_number'
  end

  def check(text, body)
    ctx = body['context'].transform_keys(&:to_sym)
    ctx[:user_input] = body['user_input']
    @rail.call(text, ctx)
  end

  def sentence(display)
    "In 2026, the figure was #{display}."
  end

  def payload(question, claim, periods: [], named: {})
    {
      'user_input' => question,
      'context' => {
        'language' => 'en',
        'user_input' => question,
        'asked' => { 'periods' => periods, 'named_values' => named, 'op' => claim['op'] },
        'claims' => [claim]
      }
    }
  end

  def claim(value, display, op, cells)
    { 'id' => 'c1', 'op' => op, 'value' => value, 'display' => display, 'unit' => nil, 'cells' => cells }
  end

  def cell(table, value, period, labels, roles)
    {
      'table_id' => table,
      'coords' => labels,
      'labels' => labels,
      'roles' => roles,
      'value' => value,
      'period' => period,
      'api_url' => "https://px.hagstofa.is/pxen/api/v1/en/x/#{table}.px",
      'web_url' => "https://px.hagstofa.is/pxen/api/v1/en/x/#{table}.px",
      'retrieved_at' => '2026-10-30T21:00:00Z'
    }
  end
end
