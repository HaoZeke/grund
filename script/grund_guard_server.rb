# frozen_string_literal: true

# Loopback vangrail server with Grund's cell-claim rail.
# Prints one JSON line: {"ok":true,"base_url":"http://127.0.0.1:9293",...}

begin
  require 'json'
  require 'vangrail'
  require_relative '../rails/ruby/grund_cell_claim_rail'
rescue LoadError => e
  warn 'checker offline: the cell-claim rail did not load.'
  warn e.message
  warn 'Install Ruby 3.1 or newer and set RUBYLIB to the vangrail checkout (the lib/ directory, not a gem).'
  warn 'This process will not listen. An unchecked rail must not look like a running checker.'
  exit 1
end

engine = Vangrail::Engine.new(
  input: [],
  context: [],
  output: [Grund::CellClaimRail.new],
  on_uncertain: :block
)
server = Vangrail::Server.new(
  front: Vangrail::Front.new(engine: engine),
  host: '127.0.0.1',
  port: 9293
)
$stdout.puts(JSON.generate('ok' => true, 'base_url' => server.base_url, 'version' => Vangrail::VERSION))
$stdout.flush
server.start
sleep
