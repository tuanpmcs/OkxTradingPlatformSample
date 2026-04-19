#pragma once

#include "feature_builder.h"
#include "feature_csv_writer.h"
#include "grpc_stream.h"
#include "market_stream.h"

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
					 GrpcTickHub&						 grpc_hub);

	void on_trades(const Trades& trades, const std::string& raw_json) override;
	void on_books5(const Books5& books5, const std::string& raw_json) override;
	void on_books(const Books& books, const std::string& raw_json) override;

private:
	void emit(StreamRecord&& record);

private:
	std::optional<double>&					  _last_price;
	std::map<std::string, std::string>& _previous_fields;
	std::unique_ptr<GrpcServerRuntime>& _grpc_server;
    std::unique_ptr<trading::FeatureCsvWriter>&		  _feature_csv_writer;
	GrpcTickHub&							  _grpc_hub;
	FeatureAccumulator					  _features;
	trading::feature_builder			  _feature_builder;
};
