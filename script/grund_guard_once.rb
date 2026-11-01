# frozen_string_literal: true

# One-shot fallback. Same JSON as POST /v1/check_output, on stdin and stdout.

begin
  require 'json'
  require 'vangrail'
  require_relative '../rails/ruby/grund_cell_claim_rail'
rescue LoadError => e
  warn 'checker offline: the cell-claim rail did not load.'
  warn e.message
  warn 'Install Ruby 3.1 or newer and set RUBYLIB to the vangrail checkout (the lib/ directory, not a gem).'
  exit 1
end

raw = $stdin.read.to_s
payload = raw.strip.empty? ? {} : JSON.parse(raw)
engine = Vangrail::Engine.new(
  input: [],
  context: [],
  output: [Grund::CellClaimRail.new],
  on_uncertain: :block
)
front = Vangrail::Front.new(engine: engine)
result = front.check_output(payload)
$stdout.puts(JSON.generate(result))
exit(result['status'] == 'blocked' ? 2 : (result['certain'] == false ? 3 : 0))
