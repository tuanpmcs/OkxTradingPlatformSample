#pragma once

#include "market_data.grpc.pb.h"
#include "market_stream.h"
#include "subscription.h"

#include <chrono>
#include <condition_variable>
#include <deque>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

#include <grpcpp/grpcpp.h>

class GrpcTickHub
{
public:
	struct Subscriber
	{
		std::mutex				mutex;
		std::condition_variable cv;
		std::deque<std::shared_ptr<const StreamRecord>> queue;
		bool					closed{false};

		bool wait_pop(std::shared_ptr<const StreamRecord>& event, std::chrono::milliseconds timeout);
	};

public:
	std::shared_ptr<Subscriber> add_subscriber();
	void remove_subscriber(const std::shared_ptr<Subscriber>& target);
	void broadcast(StreamRecord&& event);
	void shutdown();

private:
	std::mutex								 _mutex;
	std::vector<std::shared_ptr<Subscriber>> _subscribers;
};

class MarketDataServiceImpl final : public marketstream::MarketData::Service
{
public:
	MarketDataServiceImpl(GrpcTickHub& hub, RuntimeSubscriptionRegistry* runtime_subscriptions = nullptr);

	grpc::Status Subscribe(grpc::ServerContext* context,
						   const marketstream::SubscribeRequest* request,
						   grpc::ServerWriter<marketstream::Tick>* writer) override;

private:
	GrpcTickHub&				 _hub;
	RuntimeSubscriptionRegistry* _runtime_subscriptions{nullptr};
};

class GrpcServerRuntime
{
public:
	GrpcServerRuntime(MarketDataServiceImpl& service, unsigned short port);
	~GrpcServerRuntime();

	void start();
	void stop();

private:
	MarketDataServiceImpl&		  _service;
	unsigned short				  _port;
	std::unique_ptr<grpc::Server> _server;
	std::thread					  _thread;
	bool						  _stopped{false};
};
