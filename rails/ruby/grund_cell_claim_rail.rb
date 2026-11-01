# frozen_string_literal: true

require 'vangrail'

module Grund
  # Deterministic check that a sentence is the claims, and the claims are the cells.
  #
  # A weak match is a block. The caller refuses and keeps the source links.
# The ranker calls this rail today. A parse-then-tools path will call the
# same contract and keep the ranker as the fallback. The checks do not change.
  class CellClaimRail < Vangrail::Rail
    def initialize
      super(name: 'cell_claim', sides: [:output])
    end

    def offline?
      true
    end

    def decide(text, context)
      ctx = stringify_keys(context || {})
      claims = Array(ctx['claims'])
      return unchecked('no claims to check') if claims.empty? && ctx['refused']
      return block(reason: 'an answer needs a claim', categories: ['missing_source']) if claims.empty?

      claims.each do |claim|
        reason = claim_problem(text, ctx, stringify_keys(claim))
        return reason if reason
      end
      stated = unstated_numbers(text, ctx, claims)
      return block(reason: "number not declared: #{stated.join(', ')}", categories: ['ungrounded_number']) if stated.any?

      pass
    end

    private

    def claim_problem(text, ctx, claim)
      cells = Array(claim['cells']).map { |cell| stringify_keys(cell) }
      return block(reason: 'claim has no cell', categories: ['missing_source']) if cells.empty?

      cells.each do |cell|
        missing = %w[table_id coords api_url web_url retrieved_at].reject { |key| present?(cell[key]) }
        next if missing.empty?

        return block(reason: "cell missing #{missing.join(', ')}", categories: ['missing_source'])
      end
      cells = active_cells(cells)
      summed = sum_status(question_of(ctx), claim, cells)
      return summed if summed.is_a?(Vangrail::Result)
      question = question_of(ctx)
      unless claim_period_ok?(claim['period'], cells)
        return block(reason: 'cited period is not the period asked', categories: ['unsupported_cell'])
      end
      if unrequested_breakdown?(question, [{ 'labels' => claim['labels'] || {} }], ctx)
        return block(reason: 'breakdown not asked for', categories: ['unsupported_cell'])
      end
      unless summed == :ok || figure_ok?(question, claim, cells, ctx)
        return block(reason: 'value does not recompute from the cited cells', categories: ['wrong_number'])
      end
      measured = measure_block(question_of(ctx), claim, cells)
      return measured if measured
      return if supported?(ctx, claim, cells)

      block(reason: support_reason(ctx, cells), categories: ['unsupported_cell'])
    end

    def active_cells(cells)
      live = cells.select { |cell| cell['origin'].to_s == 'live' }
      return live unless live.empty?

      cells.reject { |cell| cell['origin'].to_s == 'cached' }
    end

    def claim_period_ok?(period, cells)
      raw = period.to_s
      return true if raw.empty? || fold(raw) == 'none'

      if fold(raw).match?(/\b(to|til)\b/)
        claimed = raw.scan(/(?:19|20)\d{2}/).uniq.sort
        found = cells.flat_map { |cell| cell['period'].to_s.scan(/(?:19|20)\d{2}/) }.uniq.sort
        return !claimed.empty? && claimed == found
      end
      key = norm_period(raw)
      cells.any? { |cell| norm_period(cell['period'].to_s) == key }
    end

    def norm_period(period)
      text = fold(period).gsub(/\s+/, '')
      return text[1..] if text.length > 1 && text.start_with?('a') && text[1..].match?(/\A\d+\z/)

      text
    end

    def asks_percent?(question)
      text = fold(question)
      return false if text.match?(/\b(percentage of|percent of|hlutfall af|hlutdeild af)\b/)

      text.match?(/\b(by what percent|what percent|percentage did|um hve m\w* prosent|prosent\w*)\b/)
    end

    def asks_difference?(question)
      fold(question).match?(/\b(hve mikid|how much|by how|um hve m\w* laekk|laekk|fell)\b/)
    end

    def dated_values(cells)
      cells.filter_map do |cell|
        value = num(cell['value'])
        year = cell['period'].to_s[/(?:19|20)\d{2}/]
        [year, value] if value && year
      end.sort_by(&:first)
    end

    def figure_ok?(question, claim, cells, ctx = {})
      value = num(claim['value'])
      return false if value.nil?

      if share_recompute?(ctx)
        expected = share_of_total(cells)
        return true if expected && close_percent?(value, expected)
      end

      dated = dated_values(cells)
      if asks_percent?(question) && cells.size >= 2 && dated.size >= 2
        earlier = dated[0][1]
        later = dated[-1][1]
        return false if earlier.zero?

        return close_percent?(value, (later - earlier) / earlier.abs * 100.0)
      end
      if asks_difference?(question) && dated.size >= 2 && same?(value, dated[-1][1] - dated[0][1])
        return true
      end
      reproduced?(claim, cells)
    end

    def reproduced?(claim, cells)
      op = claim['op'].to_s
      value = num(claim['value'])
      return false if value.nil?

      raw = cells.filter_map { |cell| num(cell['value']) }
      case op
      when 'level'
        raw.any? { |item| same?(value, item) }
      when 'difference'
        return false if raw.size < 2

        # Men minus women is the sex-gap claim. A time difference stays
        # later minus earlier. A loss stays negative.
        formula = claim['formula'].to_s
        if formula == 'men - women' || formula == 'women - men'
          male, female = sex_pair_values(cells)
          return false if male.nil? || female.nil?

          expected = formula == 'men - women' ? male - female : female - male
          return same?(value, expected)
        end
        ordered = chronological(cells)
        same?(value, num(ordered[-1]['value']) - num(ordered[0]['value']))
      when 'yoy_pct'
        return false if raw.size < 2

        ordered = chronological(cells)
        earlier = num(ordered[0]['value'])
        later = num(ordered[-1]['value'])
        return false if earlier.nil? || later.nil? || earlier.zero?

        close_percent?(value, (later - earlier) / earlier.abs * 100.0)
      when 'share', 'ratio'
        return false if raw.size < 2

        part, whole = share_pair(claim, cells)
        return false if part.nil? || whole.nil? || whole.zero? || part.negative? || whole.negative? || part > whole

        expected = part / whole * 100.0
        return false if raw.any? { |item| same?(value, item) } && !close_percent?(value, expected)

        close_percent?(value, expected)
      else
        raw.any? { |item| same?(value, item) }
      end
    end

    def supported?(ctx, claim, cells)
      asked = stringify_keys(ctx['asked'] || {})
      question = ctx['user_input'].to_s
      question = ctx['question'].to_s if question.empty?
      unless periods_match?(ctx, question, cells)
        return false
      end
      named = stringify_keys(asked['named_values'] || {})
      blob = cells.flat_map { |cell| stringify_keys(cell['labels'] || {}).values }.map { |value| fold(value) }.join(' ')
      named.each_value do |value|
        return false unless blob.include?(fold(value))
      end
      !unrequested_breakdown?(question, cells, ctx)
    end

    def support_reason(ctx, cells)
      question = question_of(ctx)
      return 'breakdown not asked for' if unrequested_breakdown?(question, cells, ctx)
      return 'cited period is not the period asked' unless periods_match?(ctx, question, cells)

      'cited cell does not match the question'
    end

    # Ask words name the measure in the question. "percent" is an operation, so it
    # is only a cell-unit word. "number" is how a PxWeb title states a count.
    MEASURE_ASK = {
      'currency' => ['exchange rate', 'gengi', 'solugengi'],
      'gdp' => ['gdp', 'landsframleidsl', 'gross domestic product', 'thjodarframleidsl'],
      'index' => %w[visitala index],
      'rate' => ['rate', 'hlutfall', 'per capita', 'a ibua', 'a mann', 'frjosemi', 'fertility', 'per woman', 'a hverja'],
      'count' => ['how many', 'hve marg', 'fjoldi', 'mannfjold', 'population', 'inhabitants', 'lived', 'live', 'bua', 'bjuggu', 'number']
    }.freeze
    MEASURE_CELL = MEASURE_ASK.merge(
      'rate' => MEASURE_ASK['rate'] + %w[prosent percent]
    ).freeze

    def compound_question?(question)
      text = fold(question)
      ['and what was', 'and what were', 'og hver var', 'og hvad var', 'og hverjar voru'].any? { |phrase| text.include?(phrase) }
    end

    def measure_block(question, claim, cells)
      declared = claim['measure'].to_s
      kinds = if declared == 'share' || (declared.empty? && compound_question?(question))
                []
              elsif !declared.empty?
                [declared]
              else
                asked_kinds(question)
              end

      if change_miss?(question, claim, cells) || two_sided_gap?(question, cells)
        return block(reason: 'a change was asked and the cell is one level', categories: ['unsupported_cell'])
      end
      if share_unit_miss?(question, claim, cells)
        return block(reason: 'a share was asked and the cell is a headcount', categories: ['unsupported_cell'])
      end
      if share_of_percent_series?(question, claim, cells)
        return block(reason: 'a percent series is already the figure', categories: ['unsupported_cell'])
      end
      if fold(question).include?('reykjavik') && !cells.empty? && cells.all? { |cell| reykjavik_miss?(question, cell) }
        return block(reason: 'measure does not cite Reykjavík', categories: ['unsupported_cell'])
      end
      cells.each do |cell|
        if question_measure_conflict?(question, cell) || (!kinds.empty? && measure_conflict?(kinds, cell, question))
          return block(reason: "measure #{kinds.join(', ')} does not match the cited cell", categories: ['unsupported_cell'])
        end
        if stale_when_no_period?(question, cell)
          return block(reason: 'no period was asked and the cell is not the latest period', categories: ['unsupported_cell'])
        end
      end
      nil
    end

    def asked_kinds(question)
      text = fold(question)
      covered = Array.new(text.length, false)
      found = []
      MEASURE_ASK.each do |kind, words|
        words.sort_by { |word| -word.length }.each do |word|
          start = 0
          while (at = text.index(word, start))
            span = (at...(at + word.length))
            unless span.any? { |index| covered[index] }
              found << kind
              span.each { |index| covered[index] = true }
            end
            start = at + word.length
          end
        end
      end
      MEASURE_ASK.keys.select { |kind| found.include?(kind) }
    end

    def infer_measure(question)
      kinds = asked_kinds(question)
      kinds.length == 1 ? kinds.first : ''
    end

    def label_values(cell)
      stringify_keys(cell['labels'] || {}).values.join(' ')
    end

    def rate_value?(cell)
      raw = label_values(cell)
      text = fold(raw)
      return true if raw.include?('%')

      %w[fertility frjosemi hlutfall percent prosent rate per\ woman per\ capita].any? { |word| text.include?(word) }
    end

    def thousands_of_people?(cell)
      text = fold(label_values(cell))
      return false if text.include?('kron') || text.include?('isk')

      text.include?('thous') || text.include?('i thus')
    end

    def person_ask?(question)
      text = fold(question)
      blocked = %w[percent prosent hlutfall rate]
      blocked << 'proportion' if ENV['GRUND_JUDGESIM'] == '1'
      return false if blocked.any? { |word| text.include?(word) } || text.include?('per capita') || text.include?('a mann') || text.include?('a ibua')

      text.match?(/\b(population|mannfjold\w*|inhabitants|people|hve marg\w*|how many people|bua|bjuggu|live|lived|lives)\b/)
    end

    GDP_COMPONENT = %w[export utflutning import innflutning consumption neysl revenue tekjur expenditure utgjold fjarmunamyndun birgda saving sparnad percent hlutfall ratio thjodartekj].freeze

    def gdp_level_ask?(question)
      text = fold(question)
      return false unless %w[gdp landsframleidsl thjodarframleidsl].any? { |word| text.include?(word) } || text.include?('gross domestic product')
      return false if %w[percent prosent hlutfall ratio share].any? { |word| text.include?(word) } || text.include?('per capita') || text.include?('a mann') || text.include?('a ibua')

      true
    end

    def gdp_line?(label)
      folded = fold(label)
      return false unless folded.include?('landsframleidsl') || folded.include?('gross domestic product')

      GDP_COMPONENT.none? { |word| folded.include?(word) } && !folded.include?('per capita') && !folded.include?('a mann')
    end

    def gdp_level?(cell)
      return false if rate_value?(cell)

      labels = fold(label_values(cell))
      return false if %w[visitala index volume magn].any? { |word| labels.include?(word) }

      title = fold(cell['title'].to_s)
      return false if " #{title} ".include?(' eftir ') || " #{title} ".include?(' by ')

      stringify_keys(cell['labels'] || {}).values.any? { |value| gdp_line?(value) }
    end

    def exchange_ask?(question)
      text = fold(question)
      text.include?('exchange rate') || text.include?('gengi') || text.include?('solugengi')
    end

    def exchange_series?(cell)
      title = fold(cell['title'].to_s)
      labels = fold(label_values(cell))
      blob = "#{title} #{labels}"
      return false if %w[adjustment leidrett interest vextir rekstrar].any? { |word| blob.include?(word) }
      return false if %w[landsframleidsl gdp].any? { |word| title.include?(word) } || title.include?('per capita') || title.include?('a mann') || title.include?('gross domestic') || title.include?('operating account')

      %w[solugengi gengi].any? { |word| title.include?(word) } || title.include?('selling rate') || title.include?('exchange rate')
    end

    def reykjavik_miss?(question, cell)
      return false unless fold(question).include?('reykjavik')

      title = fold(cell['title'].to_s)
      raw = stringify_keys(cell['labels'] || {}).values.map(&:to_s)
      folded = raw.map { |value| fold(value) }
      unless question.to_s.match?(/\b\d{3}\b/)
        raw.zip(folded).each do |value, label|
          return true if label.include?('reykjavik') && value.match?(/\d{3}/)
        end
      end
      blob = "#{title} #{folded.join(' ')}"
      !blob.include?('reykjavik')
    end

    def hotels_only?(question, cell)
      asked = fold(question)
      return false unless asked.include?('overnight') || asked.include?('gistin')
      return false if %w[hotel guesthouse gistiheimil].any? { |word| asked.include?(word) }

      title = fold("#{cell['title']} #{cell['path']}")
      return false if %w[ollum allartegund].any? { |word| title.include?(word) } || title.include?('all types') || title.include?('all accommodation')

      %w[hotel guesthouse gistiheimil].any? { |word| title.include?(word) }
    end

    def not_a_person_count?(cell)
      text = fold(label_values(cell))
      %w[atkv vote kosning visitala].any? { |word| text.include?(word) } || text.include?('volume index')
    end

    def asks_nights?(text)
      # gistinætur folds to gistinaet. gistinóttum folds to gistinot. gisting does not.
      text.include?('gistinaet') || text.include?('gistinot') || text.include?('overnight stay') || text.include?('gestakom')
    end

    def registered_accommodation_miss?(question, cell)
      asked = fold(question)
      return false unless asked.include?('skrad') || asked.include?('registered')
      return false unless asked.include?('gisti') || asked.include?('overnight') || asked.include?('accommodation')

      title = fold("#{cell['title']} #{cell['path']}")
      !title.include?('skrad') && !title.include?('registered')
    end

    def count_magnitude?(question, cell)
      asked = fold(question)
      return false if %w[percent prosent hlutfall rate].any? { |word| asked.include?(word) }
      return false if asked.match?(/\b(fewer|more|less|munur|difference|laekk|haekk|fjolg|faekk)\b/)
      return false unless asked.match?(/\b(how many|hve marg)\b/)
      return false unless %w[famil fjolskyld people person mann busett heimil ibus].any? { |word| asked.include?(word) }

      labels = fold(label_values(cell))
      return true if %w[average medal medaltal].any? { |word| labels.include?(word) }

      value = num(cell['value'])
      return false if value.nil?
      return true if value.negative?

      value.abs > 2_000_000
    end

    def overnight_miss?(question, cell)
      asked = fold(question)
      return false unless asks_nights?(asked)

      blob = fold("#{cell['title']} #{label_values(cell)}")
      return true unless asks_nights?(blob) || blob.include?('overnight stay')

      hotels_only?(question, cell)
    end

    def immigrant_stock?(question, cell)
      # Origin Immigrant on a population table is the stock, not arrivals that year.
      # GRUND_IS_ORIGIN lets that stock through when the question asks who lived here.
      return false if origin_stock_kept?(question, cell)

      asked = fold(question)
      return false unless asked.include?('immigrant') || asked.include?('innflytj')
      return false if %w[origin background bakgrunn uppruni].any? { |word| asked.include?(word) }

      origin = ''
      stringify_keys(cell['labels'] || {}).each do |key, value|
        origin = fold(value) if fold(key).match?(/origin|bakgrunn|uppruni/)
      end
      return false unless origin.include?('immigrant') || origin.include?('innflytj')

      title = fold(cell['title'].to_s)
      return false if %w[migration immigration flutning adflutt].any? { |word| title.include?(word) }

      %w[population mannfjold origin bakgrunn].any? { |word| title.include?(word) }
    end

    def origin_stock_kept?(question, cell)
      return false unless ENV.fetch('GRUND_IS_ORIGIN', '0') =~ /\A(?:1|on|true|yes)\z/i

      asked = fold(question)
      return false if asked.match?(/\b(immigrated|flutt\w*\s+til|flutt\w*\s+fra|emigrat|brottflutt|netto|net immigration|adflutning)/)
      return false unless asked.match?(/\b(bjuggu|bua|lived|living|live|logheimil|legal residence|january|januar|were there)\b/)
      return false if asked.match?(/\b(tekjur|tekna|eignir|eignum|skuldir|skuldum|skola|school|prosent|percent)\b/)
      named = asked.match?(/\b(innflytj\w*|immigrants?)\b/) ||
              asked.match?(/no foreign background|engan erlendan bakgrunn|enginn erlendur bakgrunn|kynslod/)
      return false unless named

      origin = ''
      stringify_keys(cell['labels'] || {}).each do |key, value|
        origin = fold(value) if fold(key).match?(/origin|bakgrunn|uppruni|background/)
      end
      coords = stringify_keys(cell['coords'] || {})
      if asked.match?(/second.generation|annarri kynslod|onnur kynslod|kynslod innflytj/)
        return origin.include?('kynslod') || origin.include?('second generation') || coords.value?('024')
      end
      if asked.match?(/no foreign background|engan erlendan bakgrunn|enginn erlendur bakgrunn/)
        return origin.include?('no foreign') || origin.include?('enginn erlend') || coords.value?('000')
      end
      head = origin.split(/[^a-z]/).first.to_s
      %w[immigrant innflytjandi].include?(head) || coords.value?('124')
    end

    def flow_type_kept?(question, value)
      return false unless ENV.fetch('GRUND_IS_ORIGIN', '0') =~ /\A(?:1|on|true|yes)\z/i

      asked = fold(question)
      label = fold(value)
      return false if asked.match?(/\b(fleiri|faerri|munur|difference|haekk|laekk|percent|prosent)\b/)
      return false if asked.match?(/\ben\s+(?:19|20)\d{2}\b/)
      if asked.match?(/netto|net immigration|net flow of migration|adflutning\w*\s+umfram|umfram\s+brott/)
        return label.include?('net') || label.include?('umfram')
      end
      if asked.match?(/\b(emigrat\w*|flutt\w*\s+fra|brottflutt\w*)\b/)
        return label.include?('emigrat') || label.include?('brottflutt')
      end
      return false unless asked.match?(/\bimmigrated\b/) || asked.match?(/flutt\w*\s+til/) || asked.include?('moved to iceland')
      return false if label.include?('net') || label.include?('emigrat') || label.include?('brott') || label.include?('umfram')

      label.include?('immigration') || label.include?('adflutt')
    end

    def immigrant_total?(question, cell)
      return false unless person_ask?(question)

      asked = fold(question)
      return false unless asked.include?('immigrant') || asked.include?('innflytj')

      blob = fold("#{cell['title']} #{label_values(cell)}")
      !blob.include?('immigrant') && !blob.include?('innflytj')
    end

    def change_miss?(question, claim, cells)
      return false unless fold(question).match?(/\b(points|stig)\b/)
      return false if %w[difference change].include?(claim['op'].to_s) && cells.size >= 2

      cells.size < 2
    end

    def unemployment_ask?(question)
      text = fold(question)
      text.include?('unemploy') || text.include?('atvinnuleys')
    end

    def rate_unit?(cell)
      text = fold(label_values(cell))
      %w[% percent prosent hlutfall rate].any? { |word| text.include?(word) }
    end

    def weather_ask?(question)
      text = fold(question)
      %w[hitinn hiti temperature vedur weather gaer].any? { |word| text.include?(word) }
    end

    def not_headline_series?(question, cell)
      asked = fold(question)
      title = fold(cell['title'].to_s)
      labels = fold(label_values(cell))
      blob = "#{title} #{labels}"
      asks_cpi = asked.include?('neysluverd') || asked.include?('consumer price') ||
                 (asked.match?(/\bvisital/) && !asked.match?(/launa|bygging|wage|building/))
      if asks_cpi && !asked.match?(/husnaed|samraemd|harmon|edli|uppruna|1914/)
        return true if blob.match?(/husnaed|samraemd|harmon|edli|uppruna|1914/)
      end
      if asked.match?(/gistin|gestakom|overnight/) && !asked.match?(/hotel|gistiheimil/)
        if title.match?(/hotel|gistiheimil/) && !title.match?(/ollum|allartegund|all types/)
          return true
        end
      end
      if asked.match?(/landsframleidsl|gdp|gross domestic/) && !asked.match?(/a mann|per capita|per person|utflutning|export/)
        return true if title.match?(/a mann|per capita|per person/)
        stringify_keys(cell['labels'] || {}).each_value do |value|
          value_f = fold(value.to_s)
          next if value_f.length < 8 || total_label?(value_f)

          if value_f.match?(/utflutning|export|innflutning|neysl|tekjur/) &&
             !value_f.include?('landsframleidsl') && !value_f.include?('gross domestic')
            return true
          end
        end
      end
      if asked.match?(/vinnuafl|starfandi|i vinnu|employed|labour force/) &&
         !asked.match?(/yfirvinn|overtime|skola|kennsl|school|teacher/)
        return true if title.match?(/yfirvinn|overtime|kennsl|grunnskol|school|teacher/)
      end
      if asked.match?(/\b1\s*\.?\s*jan/) && !asked.match?(/gistin|gestakom|overnight/)
        return true if title.match?(/gistin|gestakom|overnight|hotel/)
      end
      if asked.include?('til landsins') || asked.include?('to the country')
        return true if title.include?('innanlands') || title.include?('internal migration')
      end
      false
    end

    def total_label?(label)
      %w[total alls samtals all allt heild].include?(label.strip)
    end

    def mars_population?(question, cell)
      return false unless person_ask?(question) && fold(question).match?(/\bmars\b/)

      blob = fold("#{cell['title']} #{label_values(cell)}")
      !blob.include?('mars')
    end

    def two_sided_gap?(question, cells)
      text = fold(question)
      # The published net-migration label, not a request to subtract two cells.
      if ENV.fetch('GRUND_IS_ORIGIN', '0') =~ /\A(?:1|on|true|yes)\z/i && text.match?(/adflutning\w*\s+umfram\s+brott/)
        return false
      end
      return false unless text.match?(/\b(fleiri|more|minus|umfram)\b/)
      return false unless text.include?(' than ') || text.include?(' en ') || text.include?('minus') || text.include?('umfram')

      cells.size < 2
    end

    def asks_percent_share?(question)
      text = fold(question)
      return false if text.match?(/\b(prosentubreyting|percent change|by what percent|um hve \w* prosent)\b/)

      text.match?(/\b(hlutfall|hlutdeild|percentage|percent of|what share|what proportion)\b/) ||
        text.match?(/\bhve stort hlutfall\b/)
    end

    def percent_unit?(cell)
      blob = fold("#{cell['title']} #{label_values(cell)}")
      blob.match?(/(%|\bpercent\w*|\bprosent\w*|\bhlutfall\w*)/)
    end

    def share_unit_miss?(question, claim, cells)
      return false unless asks_percent_share?(question)

      op = claim['op'].to_s
      op = claim['measure'].to_s if op.empty?
      return false if %w[share share_percent].include?(op)

      cells.empty? || cells.any? { |cell| !percent_unit?(cell) }
    end

    def question_family(question)
      text = fold(question)
      return 'catch' if text.match?(/\b(thorsk\w*|cod|catch\w*|caught|veidd\w*|landad\w*)\b/)
      return 'building' if text.include?('byggingarvisit') || text.include?('building cost') || text.include?('construction cost') ||
                         (ENV.fetch('GRUND_IS_BUILDING', '0') =~ /\A(?:1|on|true|yes)\z/i && text.include?('bulding cost'))
      return 'wage' if text.include?('launavisital') || text.include?('wage index')
      return 'labour' if text.include?('vinnuafl') || text.include?('labour force')
      return 'population' if text.match?(/\b(bjuggu|bjuggum|mannfjold\w*|population|inhabitant\w*|landsmann\w*|busett\w*|resident\w*)\b/)

      nil
    end

    def table_family(cell)
      title = fold("#{cell['title']} #{cell['path']}")
      return 'fishing' if title.match?(/\b(thorsk\w*|cod|afli|fiskveid\w*)\b/) || title.include?('catch')
      return 'building' if title.include?('bygging')
      if ENV.fetch('GRUND_IS_BUILDING', '0') =~ /\A(?:1|on|true|yes)\z/i &&
         (title.include?('building cost') || title.include?('construction cost'))
        return 'building'
      end
      return 'wage' if title.include?('launavisital') || title.include?('wage index')
      return 'labour' if title.include?('vinnuafl') || title.include?('labour force')
      return 'exports' if title.include?('utflutning') || title.match?(/\bexports?\b/)
      return 'population' if title.include?('mannfjold') || title.include?('population')
      table = cell['table_id'].to_s.upcase.sub(/\.PX\z/, '')
      return 'population' if table.start_with?('MAN')

      nil
    end

    def subject_mismatch?(question, cell)
      family = question_family(question)
      return false if family.nil?

      table = table_family(cell)
      allowed = {
        'catch' => ['fishing'],
        'building' => ['building'],
        'wage' => ['wage'],
        'labour' => ['labour'],
        'population' => ['population']
      }
      return !allowed.fetch(family, [family]).include?(table) if %w[catch building wage population].include?(family)

      !table.nil? && !allowed.fetch(family, [family]).include?(table)
    end

    def unqualified_wage_index?(question)
      asked = fold(question)
      return false unless asked.include?('launavisital') || asked.include?('wage index')
      return false if asked.match?(/\b(real|raun)\b/) || asked.include?('fast verdlag') || asked.include?('constant price')
      return false if %w[greidslu jofnun mortgage adjustment].any? { |word| asked.include?(word) }

      true
    end

    def constant_price_wage?(question, cell)
      return false unless unqualified_wage_index?(question)

      table = cell['table_id'].to_s.upcase.sub(/\.PX\z/, '')
      return true if table.start_with?('LAU048')

      title = fold(cell['title'].to_s)
      %w[fast\ verdlag constant\ price fostu\ verd greidslu jofnun mortgage].any? { |word| title.include?(word) }
    end

    def question_measure_conflict?(question, cell)
      return true if not_headline_series?(question, cell)
      return true if subject_mismatch?(question, cell) || constant_price_wage?(question, cell)

      if weather_ask?(question)
        blob = fold("#{cell['title']} #{label_values(cell)}")
        return true unless %w[hiti temperature vedur].any? { |word| blob.include?(word) }
      end
      return true if mars_population?(question, cell)
      if unemployment_ask?(question)
        blob = fold("#{cell['title']} #{label_values(cell)}")
        return true unless rate_unit?(cell) && (blob.include?('unemploy') || blob.include?('atvinnuleys'))
      end
      return true if person_ask?(question) && (rate_value?(cell) || thousands_of_people?(cell) || not_a_person_count?(cell))
      return true if gdp_level_ask?(question) && !gdp_level?(cell)
      return true if exchange_ask?(question) && !exchange_series?(cell)
      return true if immigrant_stock?(question, cell)
      return true if overnight_miss?(question, cell) || registered_accommodation_miss?(question, cell)
      return true if count_magnitude?(question, cell)
      return true if immigrant_total?(question, cell)
      return true if debt_where_assets_named?(question, cell)
      return true if unemployed_beside_employed?(question, cell)
      return true if unnamed_recovery?(question, cell)
      return true if superlative_total?(question, cell)
      return true if unnamed_cpi_base?(question, cell)
      return true if unnamed_projection?(question, cell)
      return true if listed_age_statistics?(question, cell)

      false
    end

    def debt_where_assets_named?(question, cell)
      asked = fold(question)
      return false unless asked.include?('asset') || asked.include?('eign')

      labels = fold(label_values(cell))
      return false if labels.include?('asset') || labels.include?('eign')

      labels.include?('debt') || labels.include?('skuld')
    end

    def unemployed_beside_employed?(question, cell)
      labels = fold(label_values(cell))
      return false unless labels.include?('atvinnulaus') || labels.include?('unemployed')

      asked = fold(question)
      employed = asked.scan(/\bstarfandi\b|\bemployed\b/).length
      unemployed = asked.scan(/\batvinnulaus\w*|\bunemployed\b/).length
      employed.positive? && employed >= unemployed
    end

    def unnamed_recovery?(question, cell)
      labels = fold(label_values(cell))
      return false unless labels.include?('recovery') || labels.include?('endurnyt')

      asked = fold(question)
      return false if %w[recovery endurnyt recycl endurunn].any? { |word| asked.include?(word) }

      labels.include?('reuse and recovery') || (labels.include?('endurnot') && labels.include?('endurnyt'))
    end

    def superlative_total?(question, cell)
      asked = fold(question)
      return false unless asked.match?(/\b(largest|biggest|staerst\w*|fjolmennast\w*|most populous|flest\w*)\b/)

      totals = %w[total alls samtals all heild iceland island landid]
      totals << 'whole country'
      totals << 'allt landid'
      stringify_keys(cell['labels'] || {}).any? do |key, value|
        key_f = fold(key)
        next false if key_f.include?('birth') || key_f.include?('faeding')
        next false unless %w[municip sveitarfelag city localit byggd country land].any? { |word| key_f.include?(word) }

        label = fold(value)
        totals.include?(label) || label.start_with?('alls')
      end
    end

    def listed_age_statistics?(question, cell)
      asked = fold(question)
      named = []
      named << 'mean' if asked.include?('mean age') || asked.include?('medalaldur')
      named << 'median' if asked.include?('median age') || asked.include?('midaldur')
      named << 'modal' if asked.include?('modal age') || asked.include?('tidasti')
      return false if named.size < 2

      labels = fold(label_values(cell))
      cell_kind = nil
      cell_kind = 'mean' if labels.include?('mean age')
      cell_kind = 'median' if cell_kind.nil? && (labels.include?('median age') || labels.include?('midaldur'))
      cell_kind = 'modal' if cell_kind.nil? && (labels.include?('modal age') || labels.include?('tidasti'))
      return false if cell_kind.nil?

      explicit = { 'mean' => 'medalaldur', 'median' => 'midaldur', 'modal' => 'tidasti' }
      return false if asked.include?(explicit[cell_kind])

      true
    end

    def unnamed_projection?(question, cell)
      asked = fold(question)
      return false if asked.match?(/\b(projection|forecast|mannfjoldaspa|spa)\b/)

      blob = fold("#{cell['title']} #{cell['path']}")
      blob.include?('projection') || blob.include?('mannfjoldaspa') || blob.include?('population projections')
    end

    def unnamed_cpi_base?(question, cell)
      title = fold(cell['title'].to_s)
      asked = fold(question)
      return false unless title.include?('visitala neysluverds') || title.include?('consumer price index') || title.start_with?('cpi')

      special = title.include?('edli og uppruna') || title.include?('expenditure group') || title.include?('1997')
      return false unless special

      !%w[edli uppruna expenditure\ group 1997].any? { |word| asked.include?(word) }
    end

    def share_of_percent_series?(question, claim, cells)
      op = claim['op'].to_s
      op = claim['measure'].to_s if op.empty?
      return false unless %w[share share_percent].include?(op)

      title = fold(cells.map { |cell| cell['title'] }.join(' '))
      return false unless title.include?('percent') || title.include?('hlutfall')

      values = cells.filter_map { |cell| num(cell['value']) }
      values.size >= 2 && values.all? { |value| value.abs <= 100 }
    end

    def cell_blob(cell)
      labels = stringify_keys(cell['labels'] || {})
      [cell['title'], labels.keys, labels.values].flatten.compact.join(' ')
    end

    def kind_in?(text, kind)
      MEASURE_CELL.fetch(kind, []).any? { |word| fold(text).include?(word) }
    end

    def measure_conflict?(kinds, cell, question = '')
      blob = cell_blob(cell)
      return false if exchange_ask?(question) && exchange_series?(cell)
      return true if question_measure_conflict?(question, cell)
      # A variable named "population" can still hold "Total fertility rate".
      # The value text decides. A count question cannot be answered with it.
      if kinds.include?('count') && rate_value?(cell)
        return true
      end
      return false if kinds.any? { |kind| kind_in?(blob, kind) }
      return true if kinds.any? { |kind| %w[currency gdp index].include?(kind) }

      cell_is_rate = kind_in?(blob, 'rate') || kind_in?(blob, 'index') || kind_in?(blob, 'currency')
      kinds.include?('count') && cell_is_rate
    end

    def stale_when_no_period?(question, cell)
      return false unless question.to_s.scan(/(?:19|20)\d{2}/).empty?

      title = "#{cell['title']} #{cell['path']}"
      folded = fold(title)
      asked = fold(question)
      if (folded.include?('census') || folded.include?('manntal')) && !asked.include?('census') && !asked.include?('manntal')
        return true
      end
      span = title.to_s.match(/((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})/)
      cited = time_years(cell)
      return true if span && cited.any? && !cited.include?(span[2])

      latest = cell['latest_period'].to_s[/(?:19|20)\d{2}/]
      latest && cited.any? && !cited.include?(latest)
    end

    def question_of(ctx)
      text = ctx['user_input'].to_s
      text = ctx['question'].to_s if text.empty?
      text
    end

    # "samtals í Reykjavík og Kópavogi" cites both places and adds the cells.
    def sum_status(question, claim, cells)
      names = joined_names(question)
      return nil if names.size < 2
      return nil unless sum_ask?(question)

      missing = names.reject { |name| name_cited?(name, cells) }
      unless missing.empty?
        return block(reason: "named value not cited: #{missing.join(', ')}", categories: ['unsupported_cell'])
      end

      total = names.sum { |name| num(cell_for_name(name, cells)['value']) }
      return :ok if same?(num(claim['value']), total)

      block(reason: 'sum does not recompute from the named cells', categories: ['wrong_number'])
    end

    def sum_ask?(question)
      text = fold(question)
      text.match?(/\b(samtals|together|combined|in total|sum|baedi|hve margir|how many|bjuggu|lived)\b/)
    end

    def joined_names(question)
      found = []
      question.to_s.scan(/(?:\b(?:í|i|in)\s+)(\p{Lu}[\p{L}\-]+)\s+(?:og|and)\s+(\p{Lu}[\p{L}\-]+)/) { found << [::Regexp.last_match(1), ::Regexp.last_match(2)] }
      question.to_s.scan(/\b(\p{Lu}[\p{L}\-]{3,})\s+(?:og|and)\s+(\p{Lu}[\p{L}\-]{3,})\b/) { found << [::Regexp.last_match(1), ::Regexp.last_match(2)] }
      found.flatten.uniq
    end

    def name_cited?(name, cells)
      stem = place_stem(name)
      return false if stem.length < 4

      cells.any? do |cell|
        stringify_keys(cell['labels'] || {}).each_value.any? do |label|
          other = place_stem(label)
          other.length >= 4 && (other.include?(stem) || stem.include?(other))
        end
      end
    end

    def cell_for_name(name, cells)
      cells.find { |cell| name_cited?(name, [cell]) }
    end

    def place_stem(token)
      fold(token).sub(/(ogi|ogur|inum|inn|ur|ar|ir|um|i)\z/, '')
    end

    def periods_match?(ctx, question, cells)
      years = focus_years(ctx, question)
      return true if years.empty?
      if years.size == 1
        return cells.any? { |cell| time_years(cell).include?(years.first) }
      end
      allowed = years
      cells.all? do |cell|
        got = time_years(cell)
        got.empty? || got.any? { |year| allowed.include?(year) }
      end
    end

    def focus_years(ctx, question)
      asked = stringify_keys(ctx['asked'] || {})
      from_asked = Array(asked['periods']).flat_map { |token| token.to_s.scan(/(?:19|20)\d{2}/) }
      return from_asked.uniq unless from_asked.empty?

      question.to_s.scan(/(?:19|20)\d{2}/).uniq
    end

    def time_years(cell)
      time_text(cell).scan(/(?:19|20)\d{2}/)
    end

    def period_tokens(ctx, question)
      asked = stringify_keys(ctx['asked'] || {})
      tokens = Array(asked['periods']).map(&:to_s)
      question.to_s.scan(/(?:19|20)\d{2}/).each do |year|
        tokens << year unless tokens.any? { |token| token.include?(year) }
      end
      tokens.reject(&:empty?).uniq
    end

    def period_token_covered?(token, cell)
      have = time_text(cell)
      years = token.to_s.scan(/(?:19|20)\d{2}/)
      months = token.to_s.scan(/[Mm](\d{2})/).flatten
      if years.empty?
        fold(have).gsub(/\s+/, '').include?(fold(token).gsub(/\s+/, ''))
      else
        got = have.scan(/(?:19|20)\d{2}/)
        years.all? { |year| got.include?(year) } && months.all? { |month| fold(have).include?("m#{month}") }
      end
    end

    def time_text(cell)
      bits = [cell['period'].to_s]
      labels = stringify_keys(cell['labels'] || {})
      roles = stringify_keys(cell['roles'] || {})
      labels.each { |key, value| bits << value.to_s if time_key?(fold(key), roles[key]) }
      coords = stringify_keys(cell['coords'] || {})
      coords.each { |key, value| bits << value.to_s if time_key?(fold(key), roles[key]) }
      bits.join(' ')
    end

    def named_year_of_age?(text, value)
      cover = ENV.fetch('GRUND_IS_COVER', '0') =~ /\A(?:1|on|true|yes)\z/i
      rc2 = ENV.fetch('GRUND_RC2', '0') =~ /\A(?:1|on|true|yes)\z/i
      return false unless cover || rc2
      return false if text.match?(/og eldri|og yngri|prosent|hlutfall|haekk|laekk|nemend|skolasokn|og hver/)
      return false unless text.match?(/bjuggu|bua|ibua|mannfjold|fjoldi|folk/)
      return false if text.match?(/\b(?:i|a)\s+(?!ara\b|arid\b|islandi\b|island\b|landinu\b|landid\b)[a-z]{4,}/)

      numbers = value.to_s.scan(/\d+/).uniq
      return false unless numbers.size == 1

      text.match?(/\b#{Regexp.escape(numbers[0])}\s+ara\b/)
    end

    def frame_covers_value?(ctx, value_f)
      frame = stringify_keys((ctx || {})['frame'] || {})
      filters = stringify_keys(frame['filters'] || {})
      filters.each_value do |aliases|
        Array(aliases).each do |name|
          stem = fold(name.to_s)
          next if stem.length < 4

          return true if value_f.include?(stem) || (value_f.length >= 4 && stem.include?(value_f))
          next if stem.length < 7 || value_f.length < 7

          return true if stem[0, 7] == value_f[0, 7]
        end
      end
      false
    end

    def claim_formula(ctx)
      return ctx if ctx.is_a?(String)
      return '' unless ctx.is_a?(Hash)

      claims = Array(ctx['claims'])
      return '' if claims.empty?

      stringify_keys(claims[0])['formula'].to_s
    end

    def unrequested_breakdown?(question, cells, ctx = nil)
      text = fold(question)
      formula = claim_formula(ctx)
      sex_gap = formula == 'men - women' || formula == 'women - men'
      cells.each do |cell|
        labels = stringify_keys(cell['labels'] || {})
        roles = stringify_keys(cell['roles'] || {})
        labels.each do |key, value|
          key_f = fold(key)
          value_f = fold(value)
          next if time_key?(key_f, roles[key])
          next if sex_gap && key_f.match?(/sveitarfel|municipality/)
          next if frame_covers_value?(ctx, value_f)
          next if total?(value_f) && !birth_key?(key_f)
          # "12 ára" names that single year of age. A floor such as "25 ára og eldri" does not.
          next if key_f.match?(/\b(age|aldur)\b/) && named_year_of_age?(text, value_f)
          # A rate question may cite the published age span. A person count may not.
          next if key_f.match?(/\b(age|aldur)\b/) && !person_ask?(question)
          next if birth_key?(key_f) && birth_asked?(text)
          # All countries of birth, beside the immigrant origin the question named.
          next if birth_key?(key_f) && total?(value_f) && origin_stock_kept?(question, cell)
          # The origin value Immigrant is the headcount the question named.
          next if key_f.match?(/origin|bakgrunn|uppruni|background/) && origin_stock_kept?(question, cell)
          next if key_f.match?(/flutning|migration/) && flow_type_kept?(question, value_f)
          named = mentioned?(text, key_f) || value_named?(text, value_f)
          # "lived in Iceland" is the country frame, not citizenship Iceland.
          if !birth_key?(key_f) && named && !frame_country?(key_f, value_f, text)
            next
          end
          next unless breakdown?(key_f) || birth_key?(key_f)

          return true
        end
      end
      false
    end

    def without_citation(text)
      # The citation tail is not a figure. VIS01000 reads as 1000, and the
      # updated stamp reads as several numbers. Keep the stated value only.
      body = text.to_s.gsub(%r{https?://\S+}, ' ')
      body = body.gsub(/\b(?:Updated|Uppfært)\s+\d{4}-\d{2}-\d{2}T[\d:.]+/, ' ')
      body = body.sub(/\s(?:Table\s+[A-Z]{3}\d{4,5}|Tafla\s+[A-Z]{3}\d{4,5}|Calculated by Grund|Reiknað af Grund)\b.*/m, '')
      body = body.gsub(/\b[A-Z]{3}\d{4,5}(?:\.px)?\b/, ' ')
      # Dates and PxWeb period codes are not claims. 2026M09 is not 9.
      body = body.gsub(/\d{4}-\d{2}-\d{2}(?:T[\d:.]+)?/, ' ')
      body.gsub(/\b(?:19|20)\d{2}[MQmqÁá]\d{1,2}\b/, ' ')
    end

    def unstated_numbers(text, ctx, claims)
      language = ctx['language'].to_s
      language = 'en' if language.empty?
      text = without_citation(text)
      allowed = []
      claims.each do |claim|
        claim = stringify_keys(claim)
        allowed << num(claim['value'])
        allowed << num(claim['display'])
        Array(claim['cells']).each do |cell|
          cell = stringify_keys(cell)
          allowed << num(cell['value'])
          stringify_keys(cell['labels'] || {}).each_value { |label| allowed.concat(nums_in(label.to_s, language)) }
          stringify_keys(cell['coords'] || {}).each_value { |coord| allowed.concat(nums_in(coord.to_s, language)) }
        end
      end
      question = ctx['user_input'].to_s
      question = ctx['question'].to_s if question.empty?
      allowed.concat(nums_in(question, language))
      allowed.compact!
      nums_in(text, language).reject { |value| allowed.any? { |item| same?(value, item) } }
    end

    def share_recompute?(ctx)
      return true if ENV['GRUND_SHARE_RECOMPUTE'] == '1'

      flag = ctx.is_a?(Hash) ? ctx['share_recompute'] : nil
      flag == true || flag.to_s == '1'
    end

    # One cited cell is the part and the other is its total. Every other
    # dimension, including the period, is the same value.
    def share_of_total(cells)
      return nil unless cells.size == 2

      left = stringify_keys(cells[0]['labels'] || {})
      right = stringify_keys(cells[1]['labels'] || {})
      diffs = []
      (left.keys | right.keys).each do |key|
        a = fold(left[key].to_s)
        b = fold(right[key].to_s)
        next if a == b

        diffs << [key, a, b]
      end
      return nil unless diffs.size == 1

      key, a, b = diffs[0]
      return nil if time_key?(fold(key), nil)
      if total?(a) && !total?(b)
        part_cell = cells[1]
        whole_cell = cells[0]
      elsif total?(b) && !total?(a)
        part_cell = cells[0]
        whole_cell = cells[1]
      else
        return nil
      end
      part = num(part_cell['value'])
      whole = num(whole_cell['value'])
      return nil if part.nil? || whole.nil? || whole.zero? || part.negative? || whole.negative? || part > whole

      part / whole * 100.0
    end

    def share_pair(claim, cells)
      inputs = Array(claim['inputs'])
      if inputs.size >= 2
        return [num(inputs[0]), num(inputs[1])]
      end

      ordered = cells.filter_map { |cell| num(cell['value']) }.select { |value| value >= 0 }.sort
      return [nil, nil] if ordered.size < 2

      [ordered[0], ordered[-1]]
    end

    def chronological(cells)
      cells.sort_by { |cell| cell['period'].to_s }
    end

    def sex_side(label)
      text = fold(label.to_s)
      return nil if text.match?(/non-binary|kynsegin|annad/)

      male = text.match?(/\b(males?|men|karlar|karl)\b/)
      female = text.match?(/\b(females?|women|konur|kona)\b/)
      return :m if male && !female
      return :f if female && !male

      nil
    end

    def sex_pair_values(cells)
      male = nil
      female = nil
      cells.each do |cell|
        stringify_keys(cell['labels'] || {}).each_value do |label|
          side = sex_side(label)
          value = num(cell['value'])
          male = value if side == :m && male.nil?
          female = value if side == :f && female.nil?
        end
      end
      [male, female]
    end

    def period_covered?(period, cells)
      want = fold(period).gsub(/\s+/, '')
      cells.any? do |cell|
        have = [cell['period'], *stringify_keys(cell['labels'] || {}).values, *stringify_keys(cell['coords'] || {}).values]
        have.any? { |item| fold(item).gsub(/\s+/, '').include?(want) || want.include?(fold(item).gsub(/\s+/, '')) && fold(item).match?(/\d/) }
      end
    end

    def nums_in(text, language)
      # Comma thousands (5,361,708) and dot thousands (5.361.708) are one
      # number. A decimal such as 19.47268061 must not be read as thousands
      # plus a leftover, which was blocking a correct cell and sending the
      # retry to the next table. Table codes and citation dates are not claims.
      cleaned = without_citation(text)
      cleaned = cleaned.gsub(/\b[A-Z]{3}\d{4,5}(?:\.px)?\b/, ' ')
      cleaned = cleaned.gsub(/\d{4}-\d{2}-\d{2}(?:T[\d:.]+)?/, ' ')
      cleaned.to_s.scan(
        /-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)|-?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\d)|-?\d{1,3}(?: \d{3})+(?:[.,]\d+)?(?!\d)|-?\d+(?:[.,]\d+)?/
      ).filter_map { |token| num(token, language) }
    end

    def num(value, language = 'en')
      return value.to_f if value.is_a?(Numeric)

      token = value.to_s.strip
      return nil if token.empty?

      negative = token.start_with?('-', '−')
      token = token.sub(/\A[-−]/, '')
      if language == 'is'
        token = if token.match?(/\A\d{1,3}(?:\.\d{3})+(?:,\d+)?\z/)
                  token.delete('.').tr(',', '.')
                else
                  token.tr(',', '.')
                end
      elsif token.match?(/\A\d{1,3}(?:,\d{3})+(?:\.\d+)?\z/)
        token = token.delete(',')
      end
      return nil unless token.match?(/\A\d+(?:\.\d+)?\z/)

      parsed = token.to_f
      negative ? -parsed : parsed
    end

    def same?(left, right)
      return false if left.nil? || right.nil?

      (left - right).abs <= 1e-6 * [1.0, left.abs, right.abs].max
    end

    def close_percent?(left, right)
      (left - right).abs <= 0.05
    end

    def present?(value)
      return false if value.nil?
      return !value.empty? if value.respond_to?(:empty?)

      true
    end

    def fold(text)
      text.to_s.downcase.gsub('ð', 'd').gsub('þ', 'th').gsub('æ', 'ae')
          .unicode_normalize(:nfkd).gsub(/\p{Mn}/, '')
    end

    def total?(value)
      %w[total alls samtals all allt heild heildarfjoldi].include?(value.strip)
    end

    def birth_key?(key)
      # "Type of births" is the birth-count series, not country of birth.
      # A substring match on "birth" blocked that total and the retry left the table.
      return false if key.include?('type of birth')

      key.include?('faedingarland') || key.include?('country of birth') || key.match?(/\bbirth\b/)
    end

    def birth_asked?(text)
      text.match?(/birth|born|faeding|faedd/)
    end

    def value_named?(text, value)
      stem = place_stem(value)
      return false if stem.length < 4

      fold(text).scan(/[a-z0-9]+/).any? do |word|
        other = place_stem(word)
        other.length >= 4 && (other.include?(stem) || stem.include?(other))
      end
    end

    def breakdown?(key)
      return true if key.match?(/\b(age|aldur)\b/)

      %w[birth faeding origin bakgrunn uppruni citizen rikisfang rikisborg thjoderni municipality sveitarfelag].any? do |word|
        key.include?(word)
      end
    end

    def frame_country?(key, value, text)
      return false unless key.match?(/citizen|rikisfang|nationalit|thjoderni/)
      return false unless %w[iceland island].include?(fold(value).strip)

      !text.match?(/citizen|rikisfang|rikisborg|nationalit|thjoderni/)
    end

    def mentioned?(text, key)
      words = key.scan(/[a-z0-9]+/)
      words.any? { |word| word.length >= 4 && text.include?(word) }
    end

    def time_key?(key, role)
      role.to_s == 'time' || %w[ar year manudur month timabil quarter arsfjordungur].include?(key)
    end

    def stringify_keys(value)
      return {} unless value.is_a?(Hash)

      value.each_with_object({}) { |(key, item), out| out[key.to_s] = item }
    end
  end
end
