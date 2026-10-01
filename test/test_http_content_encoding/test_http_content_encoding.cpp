#include <gtest/gtest.h>
#include <helpers/HttpContentEncoding.h>

TEST(HttpContentEncoding, DefaultAndIdentitySemantics) {
  EXPECT_TRUE(mesh::http::acceptsGzip(nullptr));
  for (const char* header : {"", " ", "identity", "br", "deflate, br"}) {
    EXPECT_FALSE(mesh::http::acceptsGzip(header)) << header;
  }
}

TEST(HttpContentEncoding, BrowserListsAndQualityValues) {
  for (const char* header : {"gzip", "gzip, deflate, br", "GZip", " gzip ; q=0.1 ",
                             "gzip;q=1.000", "*", "*;q=.5, gzip;q=0.001"}) {
    EXPECT_TRUE(mesh::http::acceptsGzip(header)) << header;
  }
  for (const char* header : {"gzip;q=0", "gzip;q=0.000", "gzip;q=0, br",
                             "gzip;q=2", "gzip;q=1.1", "gzip;q=0.1234", "gzip;q=oops",
                             "gzip;q=", "gzip;q=.5", "notgzip", "gzipish", "*;q=0"}) {
    EXPECT_FALSE(mesh::http::acceptsGzip(header)) << header;
  }
}

TEST(HttpContentEncoding, ExplicitCodingOverridesWildcardRegardlessOfOrder) {
  EXPECT_FALSE(mesh::http::acceptsGzip("*;q=1, gzip;q=0"));
  EXPECT_FALSE(mesh::http::acceptsGzip("gzip;q=0, *;q=1"));
  EXPECT_TRUE(mesh::http::acceptsGzip("*;q=0, gzip;q=1"));
  EXPECT_TRUE(mesh::http::acceptsGzip("gzip;q=1, *;q=0"));
  EXPECT_TRUE(mesh::http::acceptsGzip("gzip;other=value;q=0.5"));
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
