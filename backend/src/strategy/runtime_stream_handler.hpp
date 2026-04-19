#pragma once

#include "features/feature_builder.hpp"
#include "features/feature_csv_writer.hpp"
#include "inference/grpc_stream.hpp"
#include "inference/prediction_client.hpp"
#include "market_data/market_stream.hpp"

#include <cstdint>
#include <deque>
#include <map>
#include <memory>
#include <optional>
#include <string>

class RuntimeStreamHandler final : public MarketEventListener
{
public:
	RuntimeStreamHandler(std::optional<double>&					 last_price,
					 std::map<std::string, std::string>& previous_fields,
					 std::unique_ptr<GrpcServerRuntime>& grpc_server,
                     std::unique_ptr<trading::FeatureCsvWriter>& feature_csv_writer,
					 PredictionClient*                     prediction_client,
					 InferenceRuntimeConfig               inference_cfg,
					 GrpcTickHub&						 grpc_hub);

	void on_trades(const Trades& trades, const std::string& raw_json) override;
	void on_books5(const Books5& books5, const std::string& raw_json) override;
	void on_books(const Books& books, const std::string& raw_json) override;

private:
	void emit(StreamRecord&& record);
	void attach_prediction(StreamRecord& record,
						   const std::string& symbol,
						   const std::string& channel,
						   std::int64_t	   ts_ms,
						   double		   bid_px,
						   double		   ask_px,
						   double		   bid_sz,
						   double		   ask_sz);

private:
	std::optional<double>&					  _last_price;
	std::map<std::string, std::string>& _previous_fields;
	std::unique_ptr<GrpcServerRuntime>& _grpc_server;
    std::unique_ptr<trading::FeatureCsvWriter>&		  _feature_csv_writer;
	PredictionClient*					  _prediction_client{nullptr};
	InferenceRuntimeConfig				  _inference_cfg;
	std::deque<marketstream::PricePoint> _inference_points;
	std::int64_t						  _last_inference_ts_ms{0};
	GrpcTickHub&							  _grpc_hub;
	FeatureAccumulator					  _features;
	trading::FeatureBuilder			  _feature_builder;
};
