#include "runtime_stream_handler.h"

#include <cstdint>
#include <utility>

RuntimeStreamHandler::RuntimeStreamHandler(std::optional<double>&					 last_price,
									   std::map<std::string, std::string>& previous_fields,
									   std::unique_ptr<CsvTickWriter>&	 csv_writer,
									   std::unique_ptr<GrpcServerRuntime>& grpc_server,
									   GrpcTickHub&						 grpc_hub,
									   const std::string&				 feature_csv_path)
	: _last_price(last_price)
	, _previous_fields(previous_fields)
	, _csv_writer(csv_writer)
	, _grpc_server(grpc_server)
	, _grpc_hub(grpc_hub)
	, _features(5000)
	, _feature_builder(trading::feature_builder::config{100, true})
{
	if (!feature_csv_path.empty())
	{
		_feature_csv_writer = std::make_unique<trading::feature_csv_writer>(feature_csv_path);
	}
}

void RuntimeStreamHandler::on_trades(const Trades& trades, const std::string& raw_json)
{
	for (const auto& trade : trades)
	{
		_feature_builder.on_trade(trade);

		_features.observe_trade(trade);
		_features.prune(static_cast<std::int64_t>(trade.exchange_ts_ms));
		auto record = make_stream_record_from_trade(trade, _features.snapshot(), _last_price, raw_json);
		emit(std::move(record));
	}
}

void RuntimeStreamHandler::on_books5(const Books5& books5, const std::string& raw_json)
{
	if (_feature_csv_writer)
	{
		const auto feature = _feature_builder.on_books(books5);
		if (feature)
		{
			_feature_csv_writer->write(*feature);
		}
	}

	_features.observe_books5(books5);
	_features.prune(static_cast<std::int64_t>(books5.exchange_ts_ms));

	Books books;
	books.instrument_id = books5.instrument_id;
	books.exchange_ts_ms = books5.exchange_ts_ms;
	books.sequence_id = books5.sequence_id;
	books.bids.push_back(books5.bids[0]);
	books.asks.push_back(books5.asks[0]);

	auto record = make_stream_record_from_books(books, _features.snapshot(), _last_price, raw_json, "books5");
	emit(std::move(record));
}

void RuntimeStreamHandler::on_books(const Books& books, const std::string& raw_json)
{
	if (_feature_csv_writer)
	{
		const auto feature = _feature_builder.on_books(books);
		if (feature)
		{
			_feature_csv_writer->write(*feature);
		}
	}

	_features.observe_books(books);
	_features.prune(static_cast<std::int64_t>(books.exchange_ts_ms));
	auto record = make_stream_record_from_books(books, _features.snapshot(), _last_price, raw_json, "books");
	emit(std::move(record));
}

void RuntimeStreamHandler::emit(StreamRecord&& record)
{
	populate_changed_fields(record, _previous_fields);
	_previous_fields = record.fields;
	_last_price = record.price;

	if (_csv_writer)
	{
		_csv_writer->write(record);
	}

	if (_grpc_server)
	{
		_grpc_hub.broadcast(record);
	}
}
