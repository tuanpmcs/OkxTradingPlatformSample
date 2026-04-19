#include "strategy/runtime_stream_handler.hpp"

#include <cstdint>
#include <utility>

RuntimeStreamHandler::RuntimeStreamHandler(std::optional<double>& last_price,
										   std::map<std::string, std::string>& previous_fields,
										   std::unique_ptr<GrpcServerRuntime>& grpc_server,
										   std::unique_ptr<trading::FeatureCsvWriter>& feature_csv_writer,
										   PredictionClient*					  prediction_client,
										   InferenceRuntimeConfig			  inference_cfg,
										   GrpcTickHub& grpc_hub)
	: _last_price(last_price)
	, _previous_fields(previous_fields)
	, _grpc_server(grpc_server)
	, _feature_csv_writer(feature_csv_writer)
	, _prediction_client(prediction_client)
	, _inference_cfg(std::move(inference_cfg))
	, _grpc_hub(grpc_hub)
	, _features(5000)
	, _feature_builder(trading::FeatureBuilder::Config{100, true})
{
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
	attach_prediction(record,
					  books5.instrument_id,
					  "books5",
					  static_cast<std::int64_t>(books5.exchange_ts_ms),
					  books5.bids[0].price.convert_to<double>(),
					  books5.asks[0].price.convert_to<double>(),
					  books5.bids[0].quantity.convert_to<double>(),
					  books5.asks[0].quantity.convert_to<double>());
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
	if (!books.bids.empty() && !books.asks.empty())
	{
		attach_prediction(record,
						  books.instrument_id,
						  "books",
						  static_cast<std::int64_t>(books.exchange_ts_ms),
						  books.bids[0].price.convert_to<double>(),
						  books.asks[0].price.convert_to<double>(),
						  books.bids[0].quantity.convert_to<double>(),
						  books.asks[0].quantity.convert_to<double>());
	}
	emit(std::move(record));
}

void RuntimeStreamHandler::emit(StreamRecord&& record)
{
	populate_changed_fields(record, _previous_fields);
	_previous_fields = record.fields;
	_last_price = record.price;

	if (_grpc_server)
	{
		_grpc_hub.broadcast(std::move(record));
	}
}

void RuntimeStreamHandler::attach_prediction(StreamRecord&	   record,
											 const std::string& symbol,
											 const std::string& channel,
											 std::int64_t		ts_ms,
											 double				bid_px,
											 double				ask_px,
											 double				bid_sz,
											 double				ask_sz)
{
	if (!_prediction_client || _inference_cfg.mode == InferenceMode::Off)
	{
		return;
	}

	marketstream::PricePoint point;
	point.set_ts(ts_ms);
	point.set_bid_px(bid_px);
	point.set_ask_px(ask_px);
	point.set_bid_sz(bid_sz);
	point.set_ask_sz(ask_sz);

	double mid_px = record.price;
	if (bid_px > 0.0 && ask_px >= bid_px)
	{
		mid_px = 0.5 * (bid_px + ask_px);
	}
	point.set_price(mid_px);

	_inference_points.push_back(point);
	if (_inference_points.size() > _inference_cfg.max_points)
	{
		_inference_points.pop_front();
	}

	if (_inference_points.size() < _inference_cfg.min_points)
	{
		return;
	}
	if (_last_inference_ts_ms > 0 && _inference_cfg.interval_ms > 0
		&& (ts_ms - _last_inference_ts_ms) < _inference_cfg.interval_ms)
	{
		return;
	}

	_last_inference_ts_ms = ts_ms;
	const auto result = _prediction_client->predict(symbol, channel, _inference_points);
	if (!result)
	{
		return;
	}

	record.fields["pred_model"] = result->model_name;
	record.fields["pred_signal"] = result->signal;
	record.fields["pred_ret"] = std::to_string(result->predicted_return);
	record.fields["pred_price"] = std::to_string(result->predicted_price);
	record.fields["pred_detail"] = result->detail;
}
