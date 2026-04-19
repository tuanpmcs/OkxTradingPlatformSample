#pragma once 

#include "features/feature_builder.hpp"
#include <fstream>
#include <stdexcept>
#include <string>

namespace trading
{
class FeatureCsvWriter
{
public:
    explicit FeatureCsvWriter(const std::string& path);
    void write(const FeatureRow& row);
private:
    void write_header();
private:
    std::ofstream m_out;
};
}  // namespace trading
