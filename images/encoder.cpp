#include<iostream>
#include<vector>
#include<fstream>
#include<string>
#include<stdexcept>
#include <filesystem>

#define STB_IMAGE_IMPLEMENTATION
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"
#include "stb_image.h"


std::vector<uint8_t> build_header(const std::string& filename, uint32_t file_size){

    std::vector<uint8_t> header;

    //magic bytes 4bytes
    header.push_back('S');
    header.push_back('T');
    header.push_back('E');
    header.push_back('G');

    //file size 4 bytes
    for (int i = 3; i >= 0; i--) {
        header.push_back((file_size >> (i * 8)) & 0xFF); //push the file size its 32  bits long
    }

    //file name size 2 bytes
    uint16_t filename_size=filename.size();
    header.push_back((filename_size >> 8) & 0xFF); //push the high 8 bits
    header.push_back((filename_size & 0xFF)); //push the lower 8 bits

    //next is filename variable bytes
    for (char c : filename) {
        header.push_back((uint8_t)c); //push the actual file name to header
    }

    //minimum header size is 15 bytes when file name is 1 char with no extention
    return header;

}


void embed_secret(const std::vector<uint8_t>& secret,const std::string& secret_path , uint8_t* image,int height,int width){

    int index=0;
    size_t image_size = width * height * 3;

    std::vector<uint8_t> header=build_header(std::filesystem::path(secret_path).filename().string(),secret.size());

    std::cout<<" max bytes that can be stored is "<<image_size/8;

    std::vector<uint8_t> stream;
    stream.insert(stream.begin(),header.begin(),header.end()); //copy header to stream
    stream.insert(stream.end(),secret.begin(),secret.end());  //copy secret to stream 


    if(image_size<stream.size()*8){
        throw std::runtime_error("secret file is too large to embed on to target image use smaller secret file or larger image");
    }
    
    for (uint8_t byte : stream){ //loop to get each byte
        for (int i = 7; i >= 0; i--){ 
        
            image[index]=(image[index] & 0b11111110) | ((byte >> i) & 1);  //reset lsb of the image channel and then set it to the bit extracted from the secret file
            index++;
            
        }   
    }
}


std::vector<uint8_t> get_secret_file(const std::string& path){
    //this function reads the files that need to be embeded and return the bites as a vector
        std::ifstream file(path,std::ios::binary);

    if(!file){
        throw std::runtime_error("cannot open file "+ path);
    }
    
    return std::vector<uint8_t>(
        std::istreambuf_iterator<char>(file),//begining of the file
        std::istreambuf_iterator<char>()//end of the file
    ); //returns a vector[array] of bytes of the file 
}

uint8_t* get_source_image(const std::string& path,int& width,int& height,int& channel){
    //this function reads the input image and return the bites as a vector

    uint8_t* image=stbi_load(path.c_str(),&width,&height,&channel,3);

    if(image==nullptr){
        throw std::runtime_error("cannot open file "+ path);
    }
    return(image); //
}


int main(int argc, char* argv[]) {
    // argc = number of arguments including program name
    // argv[0] = program name
    // argv[1] = first argument
    // argv[2] = second argument

    if (argc < 3) {
        std::cerr << "Usage: ./encoder path/to/image.png path/to/secret.txt\n";
        return 1;
    }

    std::string image_path  = argv[1];
    std::string secret_path = argv[2];

    int width,height,channel;
    try{
        uint8_t* image=get_source_image(image_path,width,height,channel); //the source file it is a 1d array of rgbrgbrgb
        std::vector<uint8_t> secret = get_secret_file(secret_path); //the secret file

        std::cout << "Image : " << width << "x" << height << "\n";
        std::cout<<"Size "<<secret.size()<<" Bytes";

        embed_secret(secret,secret_path,image,height,width);

        int ok = stbi_write_png("output.png", width, height, 3, image, width * 3); //save img
        if (ok == 0) {
            throw std::runtime_error("failed to save output.png");
        }
        std::cout << "\nSaved to output.png\n";

        stbi_image_free(image);

    }
    catch(std::runtime_error& e){
        std::cerr<<"ERROR " <<e.what()<< "\n";

    }
}