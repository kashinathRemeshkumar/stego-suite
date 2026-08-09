#include<iostream>
#include<vector>
#include<fstream>
#include<string>
#include<stdexcept>
#include <filesystem>

#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"


struct Header {
    bool     valid=false;          // did magic bytes match?
    uint32_t file_size=0;      // size of secret file
    uint16_t filename_size=0;  // length of filename
    std::string filename="";    // the actual filename
    int index=0;               // the current index of the pointer of the image
};


uint8_t read_byte(const uint8_t* image, int &index) {
    uint8_t buffer = 0;

    for (int j = 7; j >= 0; j--) {
        uint8_t bit = image[index] & 1;   // extract LSB
        buffer = buffer | (bit << j);     // place at correct position
        index++;
    }
    return buffer;
}



Header get_head_data(const uint8_t* image){

    struct Header header;
    header.index=0;  //master index of the image
    std::string magic_byte="";

    for(int i=0;i<4;i++){
        uint8_t buffer=read_byte(image,header.index);
        magic_byte=magic_byte+char(buffer);
    }
    
    if (magic_byte[0]=='S' && magic_byte[1]=='T' && magic_byte[2]=='E' && magic_byte[3]=='G'){
        header.valid=true;
    }

    if(header.valid){
        //now get the file size 32 bits
        uint32_t file_size=0;
        for(int i=3;i>=0;i--){
            uint8_t buffer=read_byte(image,header.index);
            file_size=file_size | (buffer<<i*8);
        }
        header.file_size=file_size;

        //filename size
        uint16_t filename_size = 0;
        filename_size = read_byte(image, header.index) << 8;
        filename_size = filename_size | read_byte(image, header.index);
        header.filename_size = filename_size;

        //actual file name
        for(int i=0;i<header.filename_size;i++){
            header.filename+=char(read_byte(image,header.index));
        }    
    }

    else{
        header.valid=false;
    }

    return header;

}


void extract_secret(const uint8_t* image,int height,int width){

    struct Header header=get_head_data(image);
    std::vector<uint8_t> secret;

    if(header.valid){
        std::cout<<"extracting file \n";
        std::cout<<"file name: "<<header.filename <<"\n";
        std::cout<<"file size(bytes) "<<header.file_size<<"\n";

        for(int i = 0; i < (int)header.file_size; i++) {
            secret.push_back(read_byte(image, header.index));
        }
        std::ofstream out(header.filename, std::ios::binary);
        if (!out) throw std::runtime_error("cannot write: " + header.filename);
        out.write(reinterpret_cast<const char*>(secret.data()), secret.size());

        std::cout << "Saved to " << header.filename << "\n";
    }
    else{
        throw std::runtime_error("no hidden data found — magic bytes don't match");
    }
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

    if (argc < 2) {
        std::cerr << "Usage: ./decoder path/to/image.png \n";
        return 1;
    }

    std::string image_path  = argv[1];

    int width,height,channel;
    try{
        uint8_t* image=get_source_image(image_path,width,height,channel); //the source file it is a 1d array of rgbrgbrgb
        std::cout << "Image : " << width << "x" << height << "\n";
        extract_secret(image,height,width);
        stbi_image_free(image);
    }
    catch(std::runtime_error& e){
        std::cerr<<"ERROR " <<e.what()<< "\n";

    }
}